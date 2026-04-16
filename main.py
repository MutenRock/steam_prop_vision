# main.py - S.T.E.A.M Vision v2
# Modes : --debug (split OpenCV) | --escape (mpv fullscreen, prod)
from __future__ import annotations
import argparse, json, time, socket, subprocess, threading
from pathlib import Path

import cv2
import numpy as np

from steamcore.camera import Camera
from steamcore.recognition.pipeline import RecognitionPipeline

CONFIG_FILE  = Path(__file__).parent / "config.json"
COOLDOWN_SEC = 10
DEBUG_W, DEBUG_H = 1280, 480   # taille fenêtre debug (640 cam + 640 video)


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


def play_video_mpv(path: str) -> None:
    """Lance mpv fullscreen (mode escape)."""
    subprocess.Popen(
        ["mpv", "--fullscreen", "--no-terminal", path],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


# ── Debug video reader ────────────────────────────────────────────────────────────

class DebugVideoReader:
    """Lit une vidéo frame par frame pour l'afficher dans le panneau droit."""
    def __init__(self):
        self._cap:   cv2.VideoCapture | None = None
        self._lock   = threading.Lock()
        self._frame: np.ndarray | None = None
        self._path   = ""

    def load(self, path: str) -> None:
        with self._lock:
            if self._cap:
                self._cap.release()
            self._cap  = cv2.VideoCapture(path)
            self._path = path
            self._frame = None

    def read(self) -> np.ndarray | None:
        """Appelé à chaque itération du loop principal."""
        with self._lock:
            if self._cap is None:
                return None
            ok, frame = self._cap.read()
            if not ok:
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)  # loop
                ok, frame = self._cap.read()
            if ok:
                self._frame = frame
            return self._frame

    def stop(self) -> None:
        with self._lock:
            if self._cap:
                self._cap.release()
                self._cap = None


# ── Overlay helpers ───────────────────────────────────────────────────────────────

def draw_cam_overlay(frame: np.ndarray, result, idle_text: str) -> np.ndarray:
    out = frame.copy()
    h, w = out.shape[:2]
    # Bande noire en bas
    cv2.rectangle(out, (0, h - 48), (w, h), (0, 0, 0), -1)
    if result:
        txt   = f"{result.card_id}  score={result.score:.3f}"
        color = (0, 255, 100)
    else:
        txt   = idle_text
        color = (0, 200, 255)
    cv2.putText(out, txt, (10, h - 14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
    return out


def make_black_panel(w: int, h: int, text: str = "En attente...") -> np.ndarray:
    panel = np.zeros((h, w, 3), dtype=np.uint8)
    cv2.putText(panel, text, (20, h // 2),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (80, 80, 80), 1)
    return panel


# ── Trigger commun ────────────────────────────────────────────────────────────────

def on_detect(card: dict, sock: socket.socket, udp_port: int,
              debug_reader: DebugVideoReader | None) -> None:
    print(f"[detect] {card['id']}  \u2192  {card['label']}")

    if debug_reader:
        debug_reader.load(card["video"])
    else:
        threading.Thread(
            target=play_video_mpv, args=(card["video"],), daemon=True
        ).start()

    payload = json.dumps({
        "event": "detection",
        "card":  card["id"],
        "label": card["label"],
    }, ensure_ascii=False)
    udp_send(sock, udp_port, payload)


# ── Main ───────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug",  action="store_true",
                        help="Mode debug : fen\u00eatre split cam/video")
    parser.add_argument("--escape", action="store_true",
                        help="Mode escape room : mpv fullscreen, pas de GUI")
    args = parser.parse_args()

    debug_mode  = args.debug
    escape_mode = args.escape or (not args.debug)  # escape par défaut

    cfg       = load_config()
    cards     = {c["id"]: c for c in cfg["cards"]}
    udp_port  = cfg.get("udp_port", 5005)
    idle_text = cfg.get("idle_text", "En attente...")

    sock = make_udp_sock(udp_port)
    pipe = RecognitionPipeline(platest_dir="PLATEST")
    pipe.start()
    cam = Camera()
    cam.start()

    debug_reader = DebugVideoReader() if debug_mode else None

    if debug_mode:
        cv2.namedWindow("S.T.E.A.M Vision", cv2.WINDOW_NORMAL)
        cv2.resizeWindow("S.T.E.A.M Vision", DEBUG_W, DEBUG_H)

    print(f"[main] Mode {'DEBUG' if debug_mode else 'ESCAPE'} — en attente de détection...")

    cooldown: dict[str, float] = {}
    last_id:  str | None       = None
    HALF = DEBUG_W // 2

    try:
        while True:
            ok, frame = cam.read()
            if not ok:
                time.sleep(0.01)
                continue

            result  = pipe.process_frame(frame)
            card_id = result.card_id if result else None
            now     = time.time()

            # ── Trigger détection ──
            if card_id and card_id != last_id \
                    and now - cooldown.get(card_id, 0) >= COOLDOWN_SEC:
                card = cards.get(card_id)
                if card:
                    cooldown[card_id] = now
                    last_id = card_id
                    on_detect(card, sock, udp_port, debug_reader)
            elif not card_id:
                last_id = None

            # ── Affichage debug ──
            if debug_mode:
                cam_panel = cv2.resize(
                    draw_cam_overlay(frame, result, idle_text),
                    (HALF, DEBUG_H)
                )
                vid_frame = debug_reader.read() if debug_reader else None
                if vid_frame is not None:
                    vid_panel = cv2.resize(vid_frame, (HALF, DEBUG_H))
                else:
                    vid_panel = make_black_panel(HALF, DEBUG_H, "En attente vidéo...")

                display = np.hstack([cam_panel, vid_panel])
                cv2.imshow("S.T.E.A.M Vision", display)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

    except KeyboardInterrupt:
        print("[main] Arrêt.")
    finally:
        pipe.stop()
        cam.stop()
        if debug_reader:
            debug_reader.stop()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
