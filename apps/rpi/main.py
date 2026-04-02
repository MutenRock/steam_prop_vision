"""
apps/rpi/main.py
Point d'entrée principal S.T.E.A.M sur STYX (Pi 5 headless).

Pipeline validé BigEye :
  Picamera2 1280x720 → YOLO yolov8n.pt imgsz=320
  → confirmation 3 frames → Audio MP3 + UDP Loxone + Broadcast LAN

Usage :
  python apps/rpi/main.py
  python apps/rpi/main.py --loxone 192.168.1.50 --audio assets/audio/success.mp3
"""
from __future__ import annotations
import argparse
import signal
import sys
import time
import threading

from steamcore.camera   import Camera
from steamcore.detector import YOLODetector
from steamcore.audio    import AudioPlayer
from steamcore.udp      import send_event, HeartbeatThread, UDPListener


# ── Config par défaut ──────────────────────────────────────────────
DEFAULT_LOXONE_IP   = "192.168.1.50"   # ← à adapter
DEFAULT_LOXONE_PORT = 7777
DEFAULT_AUDIO       = "assets/audio/detection.mp3"
DEFAULT_MODEL       = "yolov8n.pt"
IMGSZ               = 320
CONF_THRESHOLD      = 0.5
CONFIRM_FRAMES      = 3               # détections consécutives avant trigger
COOLDOWN_SEC        = 3.0             # délai min entre deux triggers du même label
# ──────────────────────────────────────────────────────────────────


def parse_args():
    p = argparse.ArgumentParser(description="S.T.E.A.M Vision — STYX")
    p.add_argument("--loxone",    default=DEFAULT_LOXONE_IP,   help="IP Loxone Miniserver")
    p.add_argument("--loxport",   default=DEFAULT_LOXONE_PORT, type=int)
    p.add_argument("--audio",     default=DEFAULT_AUDIO,       help="Fichier audio à jouer")
    p.add_argument("--model",     default=DEFAULT_MODEL)
    p.add_argument("--no-udp",    action="store_true",         help="Désactiver l'envoi UDP")
    p.add_argument("--no-audio",  action="store_true",         help="Désactiver l'audio")
    p.add_argument("--no-heart",  action="store_true",         help="Désactiver heartbeat broadcast")
    return p.parse_args()


def on_udp_received(msg: str, addr: tuple):
    print(f"[UDP RX] {addr[0]} → {msg}")
    # Traiter ici les commandes Loxone : RESET, PAUSE, etc.
    if msg == "RESET":
        print("[CMD] Reset reçu — pipeline prêt pour nouveau cycle")


def main():
    args = parse_args()

    print("=" * 55)
    print("  S.T.E.A.M Vision — STYX  |  Pi 5 headless")
    print("=" * 55)
    print(f"  Loxone : {args.loxone}:{args.loxport}")
    print(f"  Audio  : {args.audio}")
    print(f"  Modèle : {args.model} imgsz={IMGSZ}")
    print(f"  Confirm: {CONFIRM_FRAMES} frames consécutives")
    print()

    # ── Services de fond ───────────────────────────────────────────
    if not args.no_heart:
        hb = HeartbeatThread(interval=5.0)
        hb.start()

    listener = UDPListener(on_message=on_udp_received)
    listener.start()

    # ── Hardware ───────────────────────────────────────────────────
    cam      = Camera(resolution=(1280, 720))
    detector = YOLODetector(
        model_path=args.model,
        imgsz=IMGSZ,
        conf=CONF_THRESHOLD,
        confirm_frames=CONFIRM_FRAMES,
    )
    audio    = AudioPlayer()

    print("[init] Démarrage caméra...")
    cam.start()
    print(f"[init] Caméra OK — backend: {cam.backend}")

    # ── Gestion Ctrl+C ─────────────────────────────────────────────
    running = True
    def shutdown(sig, frame):
        nonlocal running
        print("\n[stop] Arrêt propre...")
        running = False
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # ── Cooldown par label ─────────────────────────────────────────
    last_trigger: dict[str, float] = {}

    # ── Pipeline principal ─────────────────────────────────────────
    print("[run] Pipeline démarré — Ctrl+C pour arrêter\n")
    frame_count = 0

    while running:
        t0 = time.perf_counter()

        ok, frame = cam.read()
        if not ok or frame is None:
            time.sleep(0.01)
            continue

        frame_count += 1
        detection = detector.process(frame)

        if detection:
            label = detection.label
            conf  = detection.confidence
            now   = time.time()

            # Cooldown
            if now - last_trigger.get(label, 0.0) < COOLDOWN_SEC:
                continue
            last_trigger[label] = now

            print(f"[DETECT] ✓ {label}  conf={conf:.3f}")

            # Audio
            if not args.no_audio:
                audio.play(args.audio)

            # UDP Loxone
            if not args.no_udp:
                msg = f"STEAM_DETECT_{label.upper()}"
                send_event(msg, args.loxone, args.loxport)

        elapsed = time.perf_counter() - t0
        # Pas de sleep — on tourne à la vitesse du pipeline (~15 FPS)

    # ── Cleanup ────────────────────────────────────────────────────
    cam.stop()
    audio.stop()
    print(f"[stop] Pipeline arrêté après {frame_count} frames.")


if __name__ == "__main__":
    main()
