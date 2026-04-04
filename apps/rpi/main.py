"""
apps/rpi/main.py -- steam_card_pipeline (corrected)
Fix: PERSON_GRACE=15 frames, no confirm_frames, detect_person() bool
"""
from __future__ import annotations
import argparse
import signal
import time
import threading
import urllib.request
from enum import Enum, auto

from steamcore.camera                       import Camera
from steamcore.detector                     import YOLODetector
from steamcore.audio                        import AudioPlayer
from steamcore.video_player                 import VideoPlayer
from steamcore.rules                        import RuleEngine
from steamcore.udp                          import send_event, HeartbeatThread, UDPListener
from steamcore.recognition.card_detector    import CardDetector
from steamcore.recognition.card_recognizer  import CardRecognizer
from monitor.ws_bridge                      import start_in_thread as start_ws, push_event

DEFAULT_LOXONE_IP   = "192.168.1.50"
DEFAULT_LOXONE_PORT = 7777
DEFAULT_MODEL       = "yolov8n.pt"
IMGSZ               = 320
CONF_THRESHOLD      = 0.5

PERSON_DURATION  = 2.0
INSPECT_TIMEOUT  = 10.0
CARD_COOLDOWN    = 8.0
PERSON_GRACE     = 15


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
        elif action.type == "http":
            def _get(url=action.url):
                try:
                    urllib.request.urlopen(url, timeout=2)
                except Exception as e:
                    print("[http] " + url + " -> " + str(e))
            threading.Thread(target=_get, daemon=True).start()


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
    print("  Modele   : " + args.model + " imgsz=" + str(IMGSZ))
    print("  Person   : stable " + str(PERSON_DURATION) + "s (grace=" + str(PERSON_GRACE) + " frames)")
    print("  Inspect  : timeout " + str(INSPECT_TIMEOUT) + "s")
    print("  Cooldown : " + str(CARD_COOLDOWN) + "s apres detection")
    print("  Monitor  : ws://0.0.0.0:8889" + (" (off)" if args.no_monitor else ""))
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

    cam      = Camera(resolution=(1280, 720))
    detector = YOLODetector(model_path=args.model, imgsz=IMGSZ, conf=CONF_THRESHOLD)
    audio    = AudioPlayer("assets/audio")
    video    = VideoPlayer("assets/video")

    print("[init] Demarrage camera...")
    cam.start()
    print("[init] Camera OK - " + cam.backend)
    push_event({"type": "status", "msg": "Camera OK"})

    running = True

    def _stop(s, f):
        nonlocal running
        print("[stop] Arret propre...")
        running = False

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    state             = State.IDLE
    person_first_seen = 0.0
    person_miss_count = 0
    inspect_start     = 0.0
    last_triggered    = 0.0
    frame_count       = 0

    print("[run] Pipeline demarre - etat : IDLE")
    print()

    while running:
        ok, frame = cam.read()
        if not ok or frame is None:
            time.sleep(0.01)
            continue

        frame_count += 1
        now = time.time()

        if state == State.TRIGGERED:
            if now - last_triggered >= CARD_COOLDOWN:
                state             = State.IDLE
                person_first_seen = 0.0
                person_miss_count = 0
                print("[state] -> IDLE")
                push_event({"type": "state", "state": "IDLE"})
            continue

        person_seen = detector.detect_person(frame)

        if person_seen:
            person_miss_count = 0
            if person_first_seen == 0.0:
                person_first_seen = now
                print("[person] Joueur detecte, decompte...")
                push_event({"type": "person", "status": "seen"})
        else:
            person_miss_count += 1
            if person_miss_count >= PERSON_GRACE:
                if person_first_seen > 0.0:
                    print("[person] Joueur parti -> reset timer")
                    push_event({"type": "person", "status": "lost"})
                person_first_seen = 0.0
                person_miss_count = 0
                if state == State.INSPECTION:
                    state = State.IDLE
                    print("[state] INSPECTION -> IDLE (joueur parti)")
                    push_event({"type": "state", "state": "IDLE"})

        if state == State.IDLE:
            if person_first_seen > 0.0 and (now - person_first_seen) >= PERSON_DURATION:
                state         = State.INSPECTION
                inspect_start = now
                print("[state] -> INSPECTION")
                push_event({"type": "state", "state": "INSPECTION"})
                audio.play_random()
            continue

        if state == State.INSPECTION:
            if now - inspect_start > INSPECT_TIMEOUT:
                state             = State.IDLE
                person_first_seen = 0.0
                person_miss_count = 0
                print("[state] INSPECTION timeout -> IDLE")
                push_event({"type": "state", "state": "IDLE", "reason": "timeout"})
                continue

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
