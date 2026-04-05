"""
apps/rpi/main.py
Pipeline S.T.E.A.M -- version PersonTracker

Nouveautes :
  - PersonTracker gere presence / persistance / comptage / mouvement
  - INSPECTION reste active PERSIST_AFTER_LOSS=5s apres disparition joueur
  - Logs deplacement : gauche / droite / haut / bas / statique
  - Comptage multi-joueurs affiche en continu
"""
from __future__ import annotations
import argparse, signal, time, socket, random, subprocess, threading
from pathlib import Path
from enum import Enum, auto

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

DEFAULT_LOXONE_IP   = "192.168.1.50"
DEFAULT_LOXONE_PORT = 7777
DEFAULT_MODEL       = "yolov8n.pt"
IMGSZ               = 320
CONF_THRESHOLD      = 0.5

PERSON_DURATION     = 2.0   # secondes avant INSPECTION
PERSIST_AFTER_LOSS  = 5.0   # secondes de persistance apres disparition joueur
INSPECT_TIMEOUT     = 15.0  # timeout total INSPECTION (presence + persistance)
CARD_COOLDOWN       = 8.0
PERSON_GRACE        = 15    # frames de grace avant declenchement persistance


class State(Enum):
    IDLE       = auto()
    INSPECTION = auto()
    TRIGGERED  = auto()


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--loxone",     default=DEFAULT_LOXONE_IP)
    p.add_argument("--loxport",    default=DEFAULT_LOXONE_PORT, type=int)
    p.add_argument("--model",      default=DEFAULT_MODEL)
    p.add_argument("--rules",      default="config/rules.yaml")
    p.add_argument("--platest",    default="PLATEST")
    p.add_argument("--no-monitor", action="store_true")
    p.add_argument("--no-heart",   action="store_true")
    return p.parse_args()


def run_actions(rule_engine, card_result, audio, video, loxone_ip, loxport):
    actions = rule_engine.get_actions(card_result.card_id)
    if not actions:
        send_event(card_result.action, loxone_ip, loxport)
        push_event({"type": "udp_sent", "msg": card_result.action})
        return
    for action in actions:
        if action.type == "audio":
            audio.play_random(action.subdir)
            push_event({"type": "audio", "card": card_result.card_id})
        elif action.type == "video":
            threading.Thread(target=video.play_random,
                             args=(action.subdir,), daemon=True).start()
            push_event({"type": "video", "card": card_result.card_id})
        elif action.type == "udp":
            msg = action.message or card_result.action
            send_event(msg, loxone_ip, loxport)
            push_event({"type": "udp_sent", "msg": msg})


def main():
    args          = parse_args()
    rule_engine   = RuleEngine(args.rules)
    recognizer    = CardRecognizer(args.platest)
    card_detector = CardDetector()
    assets        = __import__("steamcore.assets", fromlist=["AssetLibrary"]).AssetLibrary("assets")

    print("=" * 55)
    print("  S.T.E.A.M Vision - STYX  |  Pi 5 headless")
    print("=" * 55)
    print("  Loxone   : " + args.loxone + ":" + str(args.loxport))
    print("  Person   : stable " + str(PERSON_DURATION) + "s -> inspection")
    print("  Persist  : " + str(PERSIST_AFTER_LOSS) + "s apres disparition")
    print("  Inspect  : timeout " + str(INSPECT_TIMEOUT) + "s")
    print("  Cooldown : " + str(CARD_COOLDOWN) + "s apres detection")
    print("  " + assets.summary())
    print("  " + rule_engine.summary())
    print("  " + recognizer.summary())
    print()

    if not args.no_monitor:
        start_ws()
        push_event({"type": "status", "msg": "Pipeline demarre"})

    if not args.no_heart:
        HeartbeatThread(interval=5.0).start()

    UDPListener(on_message=lambda msg, addr: (
        print("[UDP RX] " + addr[0] + " -> " + msg),
        push_event({"type": "udp_rx", "msg": msg})
    )).start()

    cam = Picamera2()
    cam.configure(cam.create_preview_configuration(
        main={"format": "RGB888", "size": (1280, 720)}
    ))
    cam.start()
    print("[init] Camera OK")

    detector = YOLODetector(model_path=args.model, imgsz=IMGSZ, conf=CONF_THRESHOLD)
    tracker  = PersonTracker(
        person_duration   = PERSON_DURATION,
        persist_after_loss = PERSIST_AFTER_LOSS,
        grace_frames      = PERSON_GRACE,
    )
    audio = AudioPlayer("assets/audio")
    video = VideoPlayer("assets/video")

    running = True
    def _stop(s, f):
        nonlocal running
        print("[stop] Arret propre...")
        running = False
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    state          = State.IDLE
    inspect_start  = 0.0
    last_triggered = 0.0
    frame_count    = 0
    last_move_log  = 0.0
    last_count_log = 0.0

    print("[run] Pipeline demarre - etat : IDLE")
    print()

    while running:
        frame = cam.capture_array()
        if frame is None:
            time.sleep(0.01)
            continue

        frame_count += 1
        now = time.time()

        # ── TRIGGERED : attendre cooldown ────────────────────
        if state == State.TRIGGERED:
            if now - last_triggered >= CARD_COOLDOWN:
                state = State.IDLE
                tracker.reset()
                print("[state] -> IDLE")
                push_event({"type": "state", "state": "IDLE"})
            continue

        # ── Detection personnes ──────────────────────────────
        person_frame = detector.detect_persons(frame)
        ts           = tracker.update(person_frame)

        # Log comptage toutes les 3s (mode parallele)
        if now - last_count_log > 3.0 and person_frame.count > 0:
            print("[count] " + str(person_frame.count) + " personne(s) dans le champ")
            push_event({"type": "count", "value": person_frame.count})
            last_count_log = now

        # Log mouvement toutes les 1s en INSPECTION
        if state == State.INSPECTION and now - last_move_log > 1.0:
            mv = ts.movement
            if mv.speed > 3:
                print("[move] " + mv.direction + " dx=" + str(round(mv.dx, 1)) + " dy=" + str(round(mv.dy, 1)) + " speed=" + str(round(mv.speed, 1)))
                push_event({"type": "movement", "direction": mv.direction,
                            "dx": round(mv.dx, 1), "dy": round(mv.dy, 1),
                            "speed": round(mv.speed, 1)})
            last_move_log = now

        # ── IDLE -> INSPECTION ───────────────────────────────
        if state == State.IDLE:
            if ts.ready_for_inspect:
                state         = State.INSPECTION
                inspect_start = now
                print("[state] -> INSPECTION")
                push_event({"type": "state", "state": "INSPECTION"})
                audio.play_random()
            continue

        # ── INSPECTION ───────────────────────────────────────
        if state == State.INSPECTION:

            # Timeout global
            if now - inspect_start > INSPECT_TIMEOUT:
                state = State.IDLE
                tracker.reset()
                print("[state] INSPECTION timeout -> IDLE")
                push_event({"type": "state", "state": "IDLE", "reason": "timeout"})
                continue

            # Joueur totalement absent + persistance expiree
            if ts.person_state == PersonState.ABSENT:
                state = State.IDLE
                tracker.reset()
                print("[state] INSPECTION -> IDLE (joueur absent)")
                push_event({"type": "state", "state": "IDLE", "reason": "absent"})
                continue

            # Si joueur en persistance : log restant
            if ts.person_state == PersonState.PERSISTING:
                pass  # on continue la detection, le tracker gere le timeout

            # Detection carte
            region = card_detector.detect(frame)
            if region is None:
                continue

            result = recognizer.recognize(region.warped)
            if result is None:
                continue

            print("[CARD] ok " + result.label + "  score=" + str(round(result.score, 3)) + "  matches=" + str(result.matches))
            push_event({"type": "card_detected", "card_id": result.card_id,
                        "label": result.label, "score": result.score})
            run_actions(rule_engine, result, audio, video, args.loxone, args.loxport)
            state          = State.TRIGGERED
            last_triggered = now
            print("[state] -> TRIGGERED (" + str(CARD_COOLDOWN) + "s cooldown)")
            push_event({"type": "state", "state": "TRIGGERED"})

    cam.stop()
    audio.stop()
    video.stop()
    print("[stop] Pipeline arrete apres " + str(frame_count) + " frames.")


if __name__ == "__main__":
    main()
