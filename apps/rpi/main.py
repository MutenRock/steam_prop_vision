"""
apps/rpi/main.py
Pipeline S.T.E.A.M avec moteur de règles (config/rules.yaml).

Fonctionnement :
  - Chaque frame YOLO cherche des détections
  - RuleEngine décide si le label doit déclencher (cooldown + min_duration + enabled)
  - Actions : audio aléatoire / vidéo fullscreen HDMI / UDP Loxone / HTTP
"""
from __future__ import annotations
import argparse
import signal
import time
import threading
import urllib.request

from steamcore.camera       import Camera
from steamcore.detector     import YOLODetector
from steamcore.audio        import AudioPlayer
from steamcore.video_player import VideoPlayer
from steamcore.assets       import AssetLibrary
from steamcore.rules        import RuleEngine
from steamcore.udp          import send_event, HeartbeatThread, UDPListener
from monitor.ws_bridge      import start_in_thread as start_ws, push_event

DEFAULT_LOXONE_IP   = "192.168.1.50"
DEFAULT_LOXONE_PORT = 7777
DEFAULT_MODEL       = "yolov8n.pt"
IMGSZ               = 320
CONF_THRESHOLD      = 0.5
CONFIRM_FRAMES      = 3


def parse_args():
    p = argparse.ArgumentParser(description="S.T.E.A.M Vision - STYX")
    p.add_argument("--loxone",     default=DEFAULT_LOXONE_IP)
    p.add_argument("--loxport",    default=DEFAULT_LOXONE_PORT, type=int)
    p.add_argument("--model",      default=DEFAULT_MODEL)
    p.add_argument("--rules",      default="config/rules.yaml")
    p.add_argument("--no-monitor", action="store_true")
    p.add_argument("--no-heart",   action="store_true")
    return p.parse_args()


def execute_actions(rule_engine, label, audio, video, loxone_ip, loxport):
    """Exécute toutes les actions définies pour ce label."""
    for action in rule_engine.get_actions(label):

        if action.type == "audio":
            played = audio.play_random(action.subdir)
            if played:
                push_event({"type": "audio", "label": label})

        elif action.type == "video":
            # Lancer en thread pour ne pas bloquer le pipeline
            def _play(v=video, s=action.subdir):
                v.play_random(s)
            threading.Thread(target=_play, daemon=True).start()
            push_event({"type": "video", "label": label})

        elif action.type == "udp":
            msg = action.message or f"STEAM_DETECT_{label.upper().replace(' ', '_')}"
            send_event(msg, loxone_ip, loxport)
            push_event({"type": "udp_sent", "msg": msg, "ip": loxone_ip})

        elif action.type == "http":
            def _http(url=action.url):
                try:
                    urllib.request.urlopen(url, timeout=2)
                    print(f"[http] GET {url} OK")
                except Exception as e:
                    print(f"[http] GET {url} FAIL: {e}")
            threading.Thread(target=_http, daemon=True).start()


def on_udp_received(msg: str, addr: tuple):
    print(f"[UDP RX] {addr[0]} -> {msg}")
    push_event({"type": "udp_rx", "msg": msg, "from": addr[0]})


def main():
    args = parse_args()
    assets      = AssetLibrary("assets")
    rule_engine = RuleEngine(args.rules)

    print("=" * 55)
    print("  S.T.E.A.M Vision - STYX  |  Pi 5 headless")
    print("=" * 55)
    print(f"  Loxone  : {args.loxone}:{args.loxport}")
    print(f"  Modele  : {args.model} imgsz={IMGSZ}")
    print(f"  Confirm : {CONFIRM_FRAMES} frames consecutives")
    print(f"  Monitor : ws://0.0.0.0:8889" + (" (off)" if args.no_monitor else ""))
    print(f"  {assets.summary()}")
    print(f"  {rule_engine.summary()}")
    print()

    if not args.no_monitor:
        start_ws()
        push_event({"type": "status", "msg": "Pipeline demarrage..."})

    if not args.no_heart:
        HeartbeatThread(interval=5.0).start()

    UDPListener(on_message=on_udp_received).start()

    cam      = Camera(resolution=(1280, 720))
    detector = YOLODetector(
        model_path=args.model,
        imgsz=IMGSZ,
        conf=CONF_THRESHOLD,
        confirm_frames=CONFIRM_FRAMES,
    )
    audio = AudioPlayer("assets/audio")
    video = VideoPlayer("assets/video")

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

    # Labels vus dans la frame précédente (pour reset min_duration)
    prev_seen: set[str] = set()
    frame_count = 0

    print("[run] Pipeline demarre - Ctrl+C pour arreter\n")

    while running:
        ok, frame = cam.read()
        if not ok or frame is None:
            time.sleep(0.01)
            continue

        frame_count += 1
        detection = detector.process(frame)

        current_seen: set[str] = set()

        if detection:
            label = detection.label
            conf  = detection.confidence
            now   = time.time()
            current_seen.add(label)

            if rule_engine.should_trigger(label, now):
                rule_engine.mark_triggered(label, now)
                print(f"[DETECT] v {label}  conf={conf:.3f}")
                push_event({"type": "detect", "label": label, "conf": conf})
                execute_actions(rule_engine, label, audio, video, args.loxone, args.loxport)

        # Reset min_duration pour les labels qui ont disparu
        for lost in prev_seen - current_seen:
            rule_engine.reset_seen(lost)

        prev_seen = current_seen

    cam.stop()
    audio.stop()
    video.stop()
    print(f"[stop] Pipeline arrete apres {frame_count} frames.")


if __name__ == "__main__":
    main()
