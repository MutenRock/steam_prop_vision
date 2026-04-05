"""
apps/rpi/main.py -- pipeline pilote par config/features.yaml

Mode card_first (recommande) :
  TOUJOURS scanner la carte -> si losange trouve + joueur present -> TRIGGER

Mode legacy (card_first=false) :
  Joueur present X secondes -> mode INSPECTION -> scanner carte
"""
from __future__ import annotations
import signal, time, socket, random, subprocess, threading
from pathlib import Path
from enum import Enum, auto

import yaml
from picamera2 import Picamera2

from steamcore.detector                    import YOLODetector
from steamcore.person_tracker              import PersonTracker, PersonState
from steamcore.audio                       import AudioPlayer
from steamcore.video_player                import VideoPlayer
from steamcore.rules                       import RuleEngine
from steamcore.udp                         import send_event, HeartbeatThread, UDPListener
from steamcore.recognition.card_detector   import CardDetector
from steamcore.recognition.card_recognizer import CardRecognizer
from monitor.ws_bridge                     import start_in_thread as start_ws, push_event

CONFIG_FILE = "config/features.yaml"


def load_config():
    p = Path(CONFIG_FILE)
    if not p.exists():
        print("[config] features.yaml introuvable, valeurs par defaut")
        return {}
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


class State(Enum):
    IDLE       = auto()
    INSPECTION = auto()
    TRIGGERED  = auto()


def udp_send(msg, ip, port):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.sendto(msg.encode(), (ip, port))
        print("[udp] -> " + ip + ":" + str(port) + " " + msg)
    except Exception as e:
        print("[udp] ERREUR : " + str(e))


def play_audio(audio):
    threading.Thread(target=audio.play_random, daemon=True).start()


def play_video(video):
    threading.Thread(target=video.play_random, daemon=True).start()


def run_actions(cfg, rule_engine, card_result, audio, video):
    lox_ip   = cfg.get("loxone_ip",   "192.168.1.50")
    lox_port = cfg.get("loxone_port", 7777)
    actions  = rule_engine.get_actions(card_result.card_id)
    if not actions:
        udp_send(card_result.action, lox_ip, lox_port)
        push_event({"type": "udp_sent", "msg": card_result.action})
        return
    for action in actions:
        if action.type == "audio" and cfg.get("enable_audio", True):
            audio.play_random(action.subdir)
            push_event({"type": "audio", "card": card_result.card_id})
        elif action.type == "video" and cfg.get("enable_video", True):
            threading.Thread(target=video.play_random,
                             args=(action.subdir,), daemon=True).start()
            push_event({"type": "video", "card": card_result.card_id})
        elif action.type == "udp":
            msg = action.message or card_result.action
            udp_send(msg, lox_ip, lox_port)
            push_event({"type": "udp_sent", "msg": msg})


def main():
    cfg = load_config()

    lox_ip   = cfg.get("loxone_ip",         "192.168.1.50")
    lox_port = cfg.get("loxone_port",        7777)
    card_first      = cfg.get("card_first",         True)
    require_person  = cfg.get("require_person",     True)
    person_duration = cfg.get("person_duration",    2.0)
    persist         = cfg.get("persist_after_loss", 5.0)
    inspect_timeout = cfg.get("inspect_timeout",    15.0)
    card_cooldown   = cfg.get("card_cooldown",      8.0)
    mov_tracking    = cfg.get("enable_movement_tracking", True)
    count_log       = cfg.get("enable_person_count",      True)
    heartbeat_on    = cfg.get("enable_heartbeat",         True)
    monitor_on      = cfg.get("enable_monitor",           True)
    audio_on        = cfg.get("enable_audio",             True)

    print("=" * 55)
    print("  S.T.E.A.M Vision - STYX  |  Pi 5")
    print("=" * 55)
    print("  Mode       : " + ("card_first" if card_first else "legacy (person_first)"))
    print("  Personne   : " + ("requise" if require_person else "optionnelle"))
    print("  Persist    : " + str(persist) + "s")
    print("  Cooldown   : " + str(card_cooldown) + "s")
    print("  Monitor    : " + ("ON" if monitor_on else "OFF"))
    print()

    rule_engine   = RuleEngine("config/rules.yaml")
    recognizer    = CardRecognizer("PLATEST",
                                   min_matches=cfg.get("card_min_matches", 12),
                                   threshold=cfg.get("card_score_threshold", 0.08))
    card_detector = CardDetector(min_area=cfg.get("card_min_area", 1500))

    if monitor_on:
        start_ws()

    if heartbeat_on:
        HeartbeatThread(interval=5.0).start()

    UDPListener(on_message=lambda msg, addr: (
        print("[UDP RX] " + addr[0] + " -> " + msg),
        push_event({"type": "udp_rx", "msg": msg})
    )).start()

    cam = Picamera2()
    cam.configure(cam.create_preview_configuration(
        main={"format": "RGB888",
              "size": (cfg.get("camera_width",  1280),
                       cfg.get("camera_height", 720))}
    ))
    cam.start()
    print("[init] Camera OK")

    detector = YOLODetector(
        model_path = cfg.get("yolo_model", "yolov8n.pt"),
        imgsz      = cfg.get("yolo_imgsz", 320),
        conf       = cfg.get("yolo_conf",  0.5),
    )
    tracker = PersonTracker(
        person_duration    = person_duration,
        persist_after_loss = persist,
        grace_frames       = 15,
    )
    audio = AudioPlayer("assets/audio")
    video = VideoPlayer("assets/video")

    running = True
    def _stop(s, f):
        nonlocal running
        running = False
        print("[stop] Arret propre...")
    signal.signal(signal.SIGINT,  _stop)
    signal.signal(signal.SIGTERM, _stop)

    state          = State.IDLE
    inspect_start  = 0.0
    last_triggered = 0.0
    last_count     = 0.0
    last_move      = 0.0
    frame_count    = 0

    print("[run] Pipeline demarre - IDLE")
    print()

    while running:
        frame = cam.capture_array()
        if frame is None:
            time.sleep(0.01)
            continue

        frame_count += 1
        now = time.time()

        # ── Cooldown apres trigger ────────────────────────────
        if state == State.TRIGGERED:
            if now - last_triggered >= card_cooldown:
                state = State.IDLE
                tracker.reset()
                print("[state] -> IDLE")
                push_event({"type": "state", "state": "IDLE"})
            continue

        # ── Detection personnes (toujours) ───────────────────
        pf = detector.detect_persons(frame)
        ts = tracker.update(pf)

        if count_log and now - last_count > 3.0 and pf.count > 0:
            print("[count] " + str(pf.count) + " personne(s)")
            push_event({"type": "count", "value": pf.count})
            last_count = now

        if mov_tracking and state == State.INSPECTION and now - last_move > 1.0:
            mv = ts.movement
            if mv.speed > 3:
                print("[move] " + mv.direction + " speed=" + str(round(mv.speed, 1)))
                push_event({"type": "movement", "direction": mv.direction,
                            "speed": round(mv.speed, 1)})
            last_move = now

        # ════════════════════════════════════════════════════
        # MODE CARD_FIRST (recommande)
        # Scan carte en continu, personne = validation
        # ════════════════════════════════════════════════════
        if card_first:
            region = card_detector.detect(frame)
            if region is None:
                continue

            # Valider presence joueur si requis
            if require_person and pf.count == 0:
                continue

            result = recognizer.recognize(region.warped)
            if result is None:
                continue

            print("[CARD] ok " + result.label + " score=" + str(round(result.score, 3)))
            push_event({"type": "card_detected", "card_id": result.card_id,
                        "label": result.label, "score": result.score})
            run_actions(cfg, rule_engine, result, audio, video)
            if audio_on:
                play_audio(audio)
            state          = State.TRIGGERED
            last_triggered = now
            print("[state] -> TRIGGERED (" + str(card_cooldown) + "s)")
            push_event({"type": "state", "state": "TRIGGERED"})
            continue

        # ════════════════════════════════════════════════════
        # MODE LEGACY (person_first)
        # ════════════════════════════════════════════════════
        if state == State.IDLE:
            if ts.ready_for_inspect:
                state         = State.INSPECTION
                inspect_start = now
                print("[state] -> INSPECTION")
                push_event({"type": "state", "state": "INSPECTION"})
                if audio_on:
                    play_audio(audio)
            continue

        if state == State.INSPECTION:
            if now - inspect_start > inspect_timeout:
                state = State.IDLE
                tracker.reset()
                print("[state] INSPECTION timeout -> IDLE")
                continue
            if ts.person_state == PersonState.ABSENT:
                state = State.IDLE
                tracker.reset()
                print("[state] INSPECTION -> IDLE (absent)")
                continue

            region = card_detector.detect(frame)
            if region is None:
                continue
            result = recognizer.recognize(region.warped)
            if result is None:
                continue

            print("[CARD] ok " + result.label + " score=" + str(round(result.score, 3)))
            push_event({"type": "card_detected", "card_id": result.card_id,
                        "label": result.label, "score": result.score})
            run_actions(cfg, rule_engine, result, audio, video)
            state          = State.TRIGGERED
            last_triggered = now
            print("[state] -> TRIGGERED (" + str(card_cooldown) + "s)")
            push_event({"type": "state", "state": "TRIGGERED"})

    cam.stop()
    audio.stop()
    video.stop()
    print("[stop] " + str(frame_count) + " frames traitees.")


if __name__ == "__main__":
    main()
