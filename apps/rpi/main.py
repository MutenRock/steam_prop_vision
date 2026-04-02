"""
apps/rpi/main.py
Point d'entree principal S.T.E.A.M sur STYX (Pi 5 headless).

Pipeline :
  Picamera2 1280x720 -> YOLO yolov8n.pt imgsz=320
  -> confirmation 3 frames
  -> Audio MP3 aleatoire + UDP Loxone + WS Monitor

Usage :
  bash scripts/linux_run.sh --loxone 192.168.1.50
  bash scripts/linux_run.sh --loxone 192.168.1.50 --audio-subdir ambiance
"""
from __future__ import annotations
import argparse
import signal
import time

from steamcore.camera   import Camera
from steamcore.detector import YOLODetector
from steamcore.audio    import AudioPlayer
from steamcore.assets   import AssetLibrary
from steamcore.udp      import send_event, HeartbeatThread, UDPListener
from monitor.ws_bridge  import start_in_thread as start_ws, push_event

DEFAULT_LOXONE_IP   = "192.168.1.50"
DEFAULT_LOXONE_PORT = 7777
DEFAULT_MODEL       = "yolov8n.pt"
IMGSZ               = 320
CONF_THRESHOLD      = 0.5
CONFIRM_FRAMES      = 3
COOLDOWN_SEC        = 3.0


def parse_args():
    p = argparse.ArgumentParser(description="S.T.E.A.M Vision - STYX")
    p.add_argument("--loxone",       default=DEFAULT_LOXONE_IP)
    p.add_argument("--loxport",      default=DEFAULT_LOXONE_PORT, type=int)
    p.add_argument("--model",        default=DEFAULT_MODEL)
    p.add_argument("--audio-subdir", default="", help="Sous-dossier assets/audio/")
    p.add_argument("--no-udp",       action="store_true")
    p.add_argument("--no-audio",     action="store_true")
    p.add_argument("--no-heart",     action="store_true")
    p.add_argument("--no-monitor",   action="store_true", help="Desactiver WS monitor :8889")
    return p.parse_args()


def on_udp_received(msg: str, addr: tuple):
    print(f"[UDP RX] {addr[0]} -> {msg}")
    push_event({"type": "udp_rx", "msg": msg, "from": addr[0]})
    if msg == "RESET":
        print("[CMD] Reset recu")


def main():
    args = parse_args()
    assets = AssetLibrary("assets")

    print("=" * 55)
    print("  S.T.E.A.M Vision - STYX  |  Pi 5 headless")
    print("=" * 55)
    print(f"  Loxone  : {args.loxone}:{args.loxport}")
    print(f"  Modele  : {args.model} imgsz={IMGSZ}")
    print(f"  Confirm : {CONFIRM_FRAMES} frames consecutives")
    print(f"  Monitor : ws://0.0.0.0:8889" + (" (desactive)" if args.no_monitor else ""))
    print(f"  {assets.summary()}")
    print()

    # Services de fond
    if not args.no_monitor:
        start_ws()
        push_event({"type": "status", "msg": "Pipeline demarrage..."})

    if not args.no_heart:
        HeartbeatThread(interval=5.0).start()

    UDPListener(on_message=on_udp_received).start()

    # Hardware
    cam      = Camera(resolution=(1280, 720))
    detector = YOLODetector(
        model_path=args.model,
        imgsz=IMGSZ,
        conf=CONF_THRESHOLD,
        confirm_frames=CONFIRM_FRAMES,
    )
    audio = AudioPlayer("assets/audio")

    print("[init] Demarrage camera...")
    cam.start()
    print(f"[init] Camera OK - backend: {cam.backend}")

    if not args.no_monitor:
        push_event({"type": "status", "msg": f"Camera OK - {cam.backend}"})

    running = True
    def shutdown(sig, frame):
        nonlocal running
        print("\n[stop] Arret propre...")
        running = False
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    last_trigger: dict[str, float] = {}
    frame_count = 0
    print("[run] Pipeline demarre - Ctrl+C pour arreter\n")

    while running:
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

            if now - last_trigger.get(label, 0.0) < COOLDOWN_SEC:
                continue
            last_trigger[label] = now

            print(f"[DETECT] v {label}  conf={conf:.3f}")

            # WS Monitor
            if not args.no_monitor:
                push_event({"type": "detect", "label": label, "conf": conf})

            # Audio aleatoire
            if not args.no_audio:
                played = audio.play_random(args.audio_subdir)
                if played and not args.no_monitor:
                    push_event({"type": "audio", "file": str(audio.assets_dir)})

            # UDP Loxone
            if not args.no_udp:
                msg = f"STEAM_DETECT_{label.upper()}"
                send_event(msg, args.loxone, args.loxport)
                if not args.no_monitor:
                    push_event({"type": "udp_sent", "msg": msg, "ip": args.loxone})

    cam.stop()
    audio.stop()
    print(f"[stop] Pipeline arrete apres {frame_count} frames.")


if __name__ == "__main__":
    main()
