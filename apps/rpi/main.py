"""
apps/rpi/main.py
Pipeline S.T.E.A.M — 3 états :

  IDLE ──── person stable Xs ──► INSPECTION
  INSPECTION ── carte trouvée ──► TRIGGERED
  TRIGGERED ── cooldown ────────► IDLE

Chaque état a ses propres actions (audio, vidéo, UDP).
"""
from __future__ import annotations
import argparse
import signal
import time
import threading
import urllib.request
from enum import Enum, auto

from steamcore.camera                    import Camera
from steamcore.detector                  import YOLODetector
from steamcore.audio                     import AudioPlayer
from steamcore.video_player              import VideoPlayer
from steamcore.rules                     import RuleEngine
from steamcore.udp                       import send_event, HeartbeatThread, UDPListener
from steamcore.recognition.card_detector  import CardDetector
from steamcore.recognition.card_recognizer import CardRecognizer
from monitor.ws_bridge                   import start_in_thread as start_ws, push_event

DEFAULT_LOXONE_IP   = "192.168.1.50"
DEFAULT_LOXONE_PORT = 7777
DEFAULT_MODEL       = "yolov8n.pt"
IMGSZ               = 320
CONF_THRESHOLD      = 0.5
CONFIRM_FRAMES      = 3


class State(Enum):
    IDLE       = auto()   # attente joueur
    INSPECTION = auto()   # joueur détecté, cherche une carte
    TRIGGERED  = auto()   # carte reconnue, cooldown


def parse_args():
    p = argparse.ArgumentParser(description="S.T.E.A.M Vision - STYX")
    p.add_argument("--loxone",          default=DEFAULT_LOXONE_IP)
    p.add_argument("--loxport",         default=DEFAULT_LOXONE_PORT, type=int)
    p.add_argument("--model",           default=DEFAULT_MODEL)
    p.add_argument("--rules",           default="config/rules.yaml")
    p.add_argument("--platest",         default="PLATEST")
    p.add_argument("--person-duration", default=2.0,  type=float,
                   help="Secondes de présence joueur avant inspection (défaut: 2s)")
    p.add_argument("--inspect-timeout", default=10.0, type=float,
                   help="Secondes max en mode inspection avant retour IDLE (défaut: 10s)")
    p.add_argument("--card-cooldown",   default=8.0,  type=float,
                   help="Cooldown après reconnaissance carte (défaut: 8s)")
    p.add_argument("--no-monitor",      action="store_true")
    p.add_argument("--no-heart",        action="store_true")
    return p.parse_args()


def run_actions(rule_engine, card_info, audio, video, loxone_ip, loxport):
    """Execute les actions définies dans rules.yaml pour cette carte."""
    card_id = card_info.card_id
    # Actions depuis rules.yaml (si la carte a une règle)
    actions = rule_engine.get_actions(card_id)
    if not actions:
        # Fallback : juste UDP avec trigger_action de info.yaml
        msg = card_info.trigger_action
        send_event(msg, loxone_ip, loxport)
        push_event({"type": "udp_sent", "msg": msg})
        return

    for action in actions:
        if action.type == "audio":
            audio.play_random(action.subdir)
            push_event({"type": "audio", "card": card_id})
        elif action.type == "video":
            threading.Thread(target=video.play_random,
                             args=(action.subdir,), daemon=True).start()
            push_event({"type": "video", "card": card_id})
        elif action.type == "udp":
            msg = action.message or card_info.trigger_action
            send_event(msg, loxone_ip, loxport)
            push_event({"type": "udp_sent", "msg": msg})
        elif action.type == "http":
            def _get(url=action.url):
                try:
                    urllib.request.urlopen(url, timeout=2)
                except Exception as e:
                    print(f"[http] {url} → {e}")
            threading.Thread(target=_get, daemon=True).start()


def main():
    args        = parse_args()
    rule_engine = RuleEngine(args.rules)
    recognizer  = CardRecognizer(args.platest)
    detector_card = CardDetector()
    assets      = __import__("steamcore.assets", fromlist=["AssetLibrary"]).AssetLibrary("assets")

    print("=" * 55)
    print("  S.T.E.A.M Vision - STYX  |  Pi 5 headless")
    print("=" * 55)
    print(f"  Loxone   : {args.loxone}:{args.loxport}")
    print(f"  Modele   : {args.model} imgsz={IMGSZ}")
    print(f"  Person   : stable {args.person_duration}s → inspection")
    print(f"  Inspect  : timeout {args.inspect_timeout}s")
    print(f"  Cooldown : {args.card_cooldown}s après détection")
    print(f"  Monitor  : ws://0.0.0.0:8889" + (" (off)" if args.no_monitor else ""))
    print(f"  {assets.summary()}")
    print(f"  {rule_engine.summary()}")
    print(f"  {recognizer.summary()}")
    print()

    if not args.no_monitor:
        start_ws()

    if not args.no_heart:
        HeartbeatThread(interval=5.0).start()

    UDPListener(on_message=lambda msg, addr: (
        print(f"[UDP RX] {addr[0]} → {msg}"),
        push_event({"type": "udp_rx", "msg": msg})
    )).start()

    cam      = Camera(resolution=(1280, 720))
    detector = YOLODetector(
        model_path=args.model, imgsz=IMGSZ,
        conf=CONF_THRESHOLD, confirm_frames=CONFIRM_FRAMES,
    )
    audio = AudioPlayer("assets/audio")
    video = VideoPlayer("assets/video")

    print("[init] Démarrage caméra...")
    cam.start()
    print(f"[init] Caméra OK — {cam.backend}")
    push_event({"type": "status", "msg": "Pipeline démarré"})

    running = True
    def _stop(s, f):
        nonlocal running
        print("\n[stop] Arrêt propre...")
        running = False
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    # ── Machine à états ──────────────────────────────────────────
    state              = State.IDLE
    person_first_seen  = 0.0
    inspect_start      = 0.0
    last_triggered     = 0.0
    frame_count        = 0
    prev_seen_person   = False

    print(f"[run] Pipeline démarré — état : IDLE\n")

    while running:
        ok, frame = cam.read()
        if not ok or frame is None:
            time.sleep(0.01)
            continue

        frame_count += 1
        now = time.time()

        # ─── TRIGGERED : attendre le cooldown ──────────────────
        if state == State.TRIGGERED:
            if now - last_triggered >= args.card_cooldown:
                print("[state] TRIGGERED → IDLE")
                push_event({"type": "state", "state": "IDLE"})
                state = State.IDLE
                person_first_seen = 0.0
            continue  # pas d'analyse pendant le cooldown

        # ─── Détection personne (YOLO sur 320×320) ──────────────
        detection    = detector.process(frame)
        person_seen  = detection is not None and detection.label == "person"

        # Reset timer si la personne disparaît
        if not person_seen and prev_seen_person:
            person_first_seen = 0.0
            if state == State.INSPECTION:
                print("[state] INSPECTION → IDLE (joueur parti)")
                push_event({"type": "state", "state": "IDLE"})
                state = State.IDLE

        if person_seen and person_first_seen == 0.0:
            person_first_seen = now

        prev_seen_person = person_seen

        # ─── IDLE : attendre durée de présence ──────────────────
        if state == State.IDLE:
            if person_seen and (now - person_first_seen) >= args.person_duration:
                state        = State.INSPECTION
                inspect_start = now
                print(f"[state] IDLE → INSPECTION")
                push_event({"type": "state", "state": "INSPECTION"})
                audio.play_random()   # son d'accueil
            continue

        # ─── INSPECTION : chercher une carte ────────────────────
        if state == State.INSPECTION:

            # Timeout inspection
            if now - inspect_start > args.inspect_timeout:
                print("[state] INSPECTION timeout → IDLE")
                push_event({"type": "state", "state": "IDLE", "reason": "timeout"})
                state = State.IDLE
                person_first_seen = 0.0
                continue

            # Détecter le losange dans la frame full-res
            region = detector_card.detect(frame)
            if region is None:
                continue

            # Reconnaître la carte depuis l'image normalisée
            result = recognizer.recognize(region.warped)
            if result is None:
                continue

            # ✅ Carte reconnue !
            print(f"[CARD] ✓ {result.label}  score={result.score:.3f}  matches={result.match_count}")
            push_event({
                "type": "card_detected",
                "card_id": result.card_id,
                "label": result.label,
                "score": result.score,
            })
            run_actions(rule_engine, result, audio, video, args.loxone, args.loxport)
            state          = State.TRIGGERED
            last_triggered = now
            print(f"[state] INSPECTION → TRIGGERED ({args.card_cooldown}s)")

    cam.stop()
    audio.stop()
    video.stop()
    print(f"[stop] Pipeline arrêté après {frame_count} frames.")


if __name__ == "__main__":
    main()
