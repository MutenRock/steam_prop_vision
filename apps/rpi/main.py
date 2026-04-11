"""
apps/rpi/main.py  —  S.T.E.A.M Vision STYX
Piloté par config/features.yaml

╔══════════════════════════════════════════════════════╗
║  pipeline_mode: "card"   (défaut — lance une vidéo)  ║
║  ─────────────────────────────────────────────────── ║
║  Scan continu de la carte via L1→L2→L3               ║
║  Même carte maintenue card_hold_ms (2000ms) → TRIGGER ║
║  Lecture vidéo + UDP → retour IDLE après idle_after_s ║
║  Pas de YOLO requis                                  ║
╠══════════════════════════════════════════════════════╣
║  pipeline_mode: "person"  (mode spécial — joue MP3)  ║
║  ─────────────────────────────────────────────────── ║
║  YOLO person détecté X secondes → lecture audio      ║
║  → retour IDLE après idle_after_s                    ║
╚══════════════════════════════════════════════════════╝
"""
from __future__ import annotations
import signal, time, threading
from pathlib import Path
from enum import Enum, auto

import cv2
import yaml
from picamera2 import Picamera2

from steamcore.audio                       import AudioPlayer
from steamcore.video_player                import VideoPlayer
from steamcore.rules                       import RuleEngine
from steamcore.udp                         import send_event as udp_send_raw, HeartbeatThread, UDPListener
from steamcore.recognition.fast_detector   import FastDetector
from steamcore.recognition.card_detector   import CardDetector
from steamcore.recognition.card_recognizer import CardRecognizer
from monitor.ws_bridge                     import start_in_thread as start_ws, push_event
from monitor.rule_api                      import start_in_thread as start_rule_api

CONFIG_FILE = "config/features.yaml"


def load_config():
    p = Path(CONFIG_FILE)
    if not p.exists():
        print("[config] features.yaml introuvable, valeurs par defaut")
        return {}
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


class State(Enum):
    IDLE    = auto()
    STANDBY = auto()   # vidéo en cours — aucune détection


# ── Helpers ───────────────────────────────────────────────────────

def udp_send(msg, ip, port):
    """Envoie UDP + pousse l'event sur le monitor WS."""
    try:
        udp_send_raw(msg, ip, port)
    except Exception as e:
        print("[udp] ERREUR : " + str(e))
    push_event({"type": "udp_sent", "msg": msg, "ip": ip, "port": port})


def run_actions(cfg, rule_engine, label_or_result, audio, video, card_id=None):
    """
    Dispatche les actions d'une règle (carte ou person).
    label_or_result : RecognitionResult (mode card) ou str (mode person).
    """
    lox_ip   = cfg.get("loxone_ip",   "192.168.1.50")
    lox_port = cfg.get("loxone_port", 7777)

    # Résoudre card_id / label
    if hasattr(label_or_result, "card_id"):
        cid   = label_or_result.card_id
        label = label_or_result.label
    else:
        cid   = label_or_result
        label = label_or_result

    actions = rule_engine.get_actions(cid)
    if not actions:
        msg = "STEAM_DETECT_" + cid.upper()
        udp_send(msg, lox_ip, lox_port)
        return

    for action in actions:
        if action.type == "audio" and cfg.get("enable_audio", True):
            threading.Thread(target=audio.play_random,
                             args=(action.subdir,), daemon=True).start()
            push_event({"type": "audio", "card": cid, "subdir": action.subdir})

        elif action.type == "video" and cfg.get("enable_video", True):
            threading.Thread(target=video.play_random,
                             args=(action.subdir,), daemon=True).start()
            push_event({"type": "video", "card": cid, "subdir": action.subdir})

        elif action.type == "image" and cfg.get("enable_video", True):
            from steamcore.image_player import ImagePlayer
            threading.Thread(target=ImagePlayer("assets/img").show_random,
                             args=(action.subdir,), daemon=True).start()
            push_event({"type": "image", "card": cid, "subdir": action.subdir})

        elif action.type == "udp":
            msg = action.message or ("STEAM_DETECT_" + cid.upper())
            udp_send(msg, lox_ip, lox_port)


# ══════════════════════════════════════════════════════════════════
# MODE CARD  —  L1→L2→L3, hold 2s, vidéo
# ══════════════════════════════════════════════════════════════════

def run_card_mode(cfg, cam, rule_engine, audio, video):
    card_hold_ms   = cfg.get("card_hold_ms",   2000)
    idle_after_s   = cfg.get("idle_after_s",   3.0)
    card_min_area  = cfg.get("card_min_area",  4000)
    card_min_match = cfg.get("card_min_matches", 12)
    card_threshold = cfg.get("card_score_threshold", 0.08)

    fast_detector = FastDetector(min_area=card_min_area)
    card_detector = CardDetector()
    recognizer    = CardRecognizer("PLATEST",
                                   min_matches=card_min_match,
                                   threshold=card_threshold)

    state          = State.IDLE
    last_triggered = 0.0
    hold_card_id   = None     # carte en cours de maintien
    hold_start     = 0.0      # timestamp de la première détection continue
    frame_count    = 0

    print("[card] Pipeline card — IDLE (hold=" + str(card_hold_ms) + "ms)")
    push_event({"type": "state", "state": "IDLE"})

    running = True
    def _stop(s, f):
        nonlocal running
        running = False
        print("[stop] Arret propre...")
    signal.signal(signal.SIGINT,  _stop)
    signal.signal(signal.SIGTERM, _stop)

    while running:
        frame = cam.capture_array()
        if frame is None:
            time.sleep(0.01)
            continue
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        frame_count += 1
        now = time.time()

        # ── STANDBY : vidéo en cours, aucune détection ────────
        if state == State.STANDBY:
            elapsed     = now - last_triggered
            video_done  = not video.is_playing()
            # Attendre fin de vidéo ET minimum idle_after_s (fallback si pas de vidéo)
            if video_done and elapsed >= idle_after_s:
                state        = State.IDLE
                hold_card_id = None
                hold_start   = 0.0
                print("[state] -> IDLE")
                push_event({"type": "state", "state": "IDLE"})
            continue

        # ── L1 : détection losange ────────────────────────────
        quad = fast_detector.detect(frame)
        if quad is None:
            if hold_card_id is not None:
                hold_card_id = None
                hold_start   = 0.0
            continue

        # ── L2 : matching ORB sur ROI ─────────────────────────
        roi    = quad.crop(frame)
        region = card_detector.detect(roi)
        if region is None:
            if hold_card_id is not None:
                hold_card_id = None
                hold_start   = 0.0
            continue

        # ── L3 : confirmation ─────────────────────────────────
        result = recognizer.recognize(region.warped)
        if result is None:
            if hold_card_id is not None:
                hold_card_id = None
                hold_start   = 0.0
            continue

        # ── Hold timer ────────────────────────────────────────
        if result.card_id != hold_card_id:
            # Nouvelle carte : démarre le timer
            hold_card_id = result.card_id
            hold_start   = now
            push_event({"type": "card_detected",
                        "card_id": result.card_id,
                        "label":   result.label,
                        "score":   round(result.score, 3)})
            print("[card] détectée : " + result.label +
                  "  score=" + str(round(result.score, 3)))
            continue

        held_ms = (now - hold_start) * 1000
        pct = min(100, int(held_ms / card_hold_ms * 100))
        # Feedback de progression toutes les ~200ms
        push_event({"type": "hold",
                    "card_id": result.card_id,
                    "label":   result.label,
                    "pct":     pct,
                    "held_ms": int(held_ms),
                    "target_ms": card_hold_ms})

        if held_ms < card_hold_ms:
            continue

        # ── TRIGGER ───────────────────────────────────────────
        print("[TRIGGER] " + result.label +
              "  score=" + str(round(result.score, 3)) +
              "  hold=" + str(int(held_ms)) + "ms")
        push_event({"type": "state", "state": "STANDBY"})
        run_actions(cfg, rule_engine, result, audio, video)
        state          = State.STANDBY
        last_triggered = now
        hold_card_id   = None
        hold_start     = 0.0
        print("[state] -> STANDBY (" + str(idle_after_s) + "s)")

    print("[stop] " + str(frame_count) + " frames traitees.")


# ══════════════════════════════════════════════════════════════════
# MODE PERSON  —  YOLO + audio seulement
# ══════════════════════════════════════════════════════════════════

def run_person_mode(cfg, cam, rule_engine, audio, video):
    from steamcore.detector      import YOLODetector
    from steamcore.person_tracker import PersonTracker, PersonState

    person_duration = cfg.get("person_duration",    2.0)
    persist         = cfg.get("persist_after_loss", 5.0)
    idle_after_s    = cfg.get("idle_after_s",       3.0)

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

    state          = State.IDLE
    last_triggered = 0.0
    last_count     = 0.0
    frame_count    = 0

    print("[person] Pipeline person — IDLE (duration=" + str(person_duration) + "s)")
    push_event({"type": "state", "state": "IDLE"})

    running = True
    def _stop(s, f):
        nonlocal running
        running = False
        print("[stop] Arret propre...")
    signal.signal(signal.SIGINT,  _stop)
    signal.signal(signal.SIGTERM, _stop)

    while running:
        frame = cam.capture_array()
        if frame is None:
            time.sleep(0.01)
            continue
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        frame_count += 1
        now = time.time()

        if state == State.STANDBY:
            if now - last_triggered >= idle_after_s:
                state = State.IDLE
                tracker.reset()
                print("[state] -> IDLE")
                push_event({"type": "state", "state": "IDLE"})
            continue

        pf = detector.detect_persons(frame)
        ts = tracker.update(pf)

        if now - last_count > 3.0 and pf.count > 0:
            push_event({"type": "count", "value": pf.count})
            last_count = now

        if ts.ready_for_inspect and state == State.IDLE:
            print("[person] Joueur détecté depuis " +
                  str(round(ts.presence_elapsed, 1)) + "s -> TRIGGER")
            push_event({"type": "state", "state": "STANDBY"})
            run_actions(cfg, rule_engine, "person", audio, video)
            state          = State.STANDBY
            last_triggered = now
            print("[state] -> STANDBY (" + str(idle_after_s) + "s)")

    print("[stop] " + str(frame_count) + " frames traitees.")


# ══════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════

def main():
    cfg = load_config()

    pipeline_mode = cfg.get("pipeline_mode", "card")
    monitor_on    = cfg.get("enable_monitor",   True)
    rule_api_on   = cfg.get("enable_rule_api",  True)
    heartbeat_on  = cfg.get("enable_heartbeat", True)
    listen_port   = cfg.get("udp_listen_port",  8888)

    print("=" * 55)
    print("  S.T.E.A.M Vision — STYX  |  Pi 5")
    print("=" * 55)
    print("  Mode        : " + pipeline_mode.upper())
    if pipeline_mode == "card":
        print("  Hold        : " + str(cfg.get("card_hold_ms", 2000)) + "ms")
    print("  Idle after  : " + str(cfg.get("idle_after_s", 3.0)) + "s")
    print("  Monitor WS  : " + ("ON :8889" if monitor_on else "OFF"))
    print("  Rule API    : " + ("ON :8890" if rule_api_on else "OFF"))
    print()

    rule_engine = RuleEngine("config/rules.yaml")
    audio       = AudioPlayer("assets/audio")
    video       = VideoPlayer("assets/video")

    if monitor_on:
        start_ws()
    if rule_api_on:
        start_rule_api(engine=rule_engine)
    if heartbeat_on:
        HeartbeatThread(interval=5.0).start()

    UDPListener(port=listen_port, on_message=lambda msg, addr: (
        print("[UDP RX] " + addr[0] + " -> " + msg),
        push_event({"type": "udp_rx", "msg": msg, "from": addr[0]})
    )).start()

    cam = Picamera2()
    cam.configure(cam.create_preview_configuration(
        main={"format": "RGB888",
              "size": (cfg.get("camera_width",  1280),
                       cfg.get("camera_height", 720))}
    ))
    cam.start()
    print("[init] Camera OK")

    if pipeline_mode == "person":
        run_person_mode(cfg, cam, rule_engine, audio, video)
    else:
        run_card_mode(cfg, cam, rule_engine, audio, video)

    cam.stop()
    audio.stop()
    video.stop()


if __name__ == "__main__":
    main()
