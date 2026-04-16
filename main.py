# main.py - S.T.E.A.M Vision v2
# Pipeline prod : camera -> ORB detection -> mpv + UDP broadcast
from __future__ import annotations
import json, time, socket, subprocess, threading
from pathlib import Path

from steamcore.camera import Camera
from steamcore.recognition.pipeline import RecognitionPipeline

CONFIG_FILE  = Path(__file__).parent / "config.json"
COOLDOWN_SEC = 10


def load_config() -> dict:
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def make_udp_sock(port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    return sock


def udp_send(sock: socket.socket, port: int, payload: str) -> None:
    try:
        sock.sendto(payload.encode(), ("<broadcast>", port))
    except Exception as e:
        print(f"[udp] erreur : {e}")


def play_video(path: str) -> None:
    subprocess.Popen(
        ["mpv", "--fullscreen", "--no-terminal", path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def main() -> None:
    cfg      = load_config()
    cards    = {c["id"]: c for c in cfg["cards"]}
    udp_port = cfg.get("udp_port", 5005)

    sock = make_udp_sock(udp_port)
    pipe = RecognitionPipeline(platest_dir="PLATEST")
    pipe.start()

    cam = Camera()
    cam.start()
    print("[main] Démarrage — en attente de détection...")

    cooldown: dict[str, float] = {}
    last_id:  str | None       = None

    try:
        while True:
            ok, frame = cam.read()
            if not ok:
                time.sleep(0.01)
                continue

            result = pipe.process_frame(frame)

            if result is None:
                last_id = None
                continue

            card_id = result.card_id
            now     = time.time()

            # skip si même carte toujours visible ou cooldown actif
            if card_id == last_id:
                continue
            if now - cooldown.get(card_id, 0) < COOLDOWN_SEC:
                continue

            cooldown[card_id] = now
            last_id = card_id

            card = cards.get(card_id)
            if card is None:
                print(f"[main] carte '{card_id}' non configurée, ignorée")
                continue

            print(f"[detect] {card_id}  score={result.score:.3f}  → {card['label']}")

            # Jouer la vidéo (non bloquant)
            threading.Thread(
                target=play_video, args=(card["video"],), daemon=True
            ).start()

            # UDP broadcast
            payload = json.dumps({
                "event": "detection",
                "card":  card_id,
                "label": card["label"],
                "score": round(result.score, 3),
            }, ensure_ascii=False)
            udp_send(sock, udp_port, payload)

    except KeyboardInterrupt:
        print("[main] Arrêt.")
    finally:
        pipe.stop()
        cam.stop()


if __name__ == "__main__":
    main()
