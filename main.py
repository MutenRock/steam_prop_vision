# main.py - S.T.E.A.M Vision v2
# Modes : --debug (split OpenCV) | --escape (mpv fullscreen, prod)
from __future__ import annotations
import argparse, json, os, time, socket, subprocess, threading
from pathlib import Path

import cv2
import numpy as np

from steamcore.camera import Camera
from steamcore.recognition.pipeline import RecognitionPipeline

CONFIG_FILE  = Path(__file__).parent / "config.json"
COOLDOWN_SEC = 10
DEBUG_W, DEBUG_H = 1280, 480


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
    subprocess.Popen(
        ["mpv", "--fullscreen", "--no-terminal", path],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


class DebugVideoReader:
    def __init__(self):
        self._cap:  cv2.VideoCapture | None = None
        self._lock  = threading.Lock()
        self._frame: np.ndarray | None = None

    def load(self, path: str) -> None:
        with self._lock:
            if self._cap:
                self._cap.release()
            self._cap   = cv2.VideoCapture(path)
            self._frame = None

    def read(self) -> np.ndarray | None:
        with self._lock:
            if self._cap is None:
                return None
            ok, frame = self._cap.read()
            if not ok:
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, frame = self._cap.read()
            if ok:
                self._frame = frame
            return self._frame

    def stop(self) -> None:
        with self._lock:
            if self._cap:
                self._cap.release()
                self._cap = None


def draw_cam_overlay(frame: np.ndarray, result, idle_text: str) -> np.ndarray:
    out = frame.copy()
    h, w = out.shape[:2]
    cv2.rectangle(out, (0, h - 48), (w, h), (0, 0, 0), -1)
    if result:
        txt, color = f"{result.card_id}  score={result.score:.3f}", (0, 255, 100)
    else:
        txt, color = idle_text, (0, 200, 255)
    cv2.putText(out, txt, (10, h - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
    return out


def make_black_panel(w: int, h: int, text: str = "En attente...") -> np.ndarray:
    panel = np.zeros((h, w, 3), dtype=np.uint8)
    cv2.putText(panel, text, (20, h // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (80, 80, 80), 1)
    return panel


def on_detect(card: dict, sock: socket.socket, udp_port: int,
              debug_reader: DebugVideoReader | None) -> None:
    print(f"[detect] {card['id']}  \u2192  {card['label']}")
    if debug_reader:
        debug_reader.load(card["video"])
    else:
        threading.Thread(target=play_video_mpv, args=(card["video"],), daemon=True).start()
    udp_send(sock, udp_port, json.dumps(
        {"event": "detection", "card": card["id"], "label": card["label"]},
        ensure_ascii=False))


def make_quit_button(window_name: str):
    """Affiche un bouton Quitter dans la fen\u00eatre OpenCV via trackbar hack."""
    pass  # gestion via touche 'q'


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug",  action="store_true")
    parser.add_argument("--escape", action="store_true")
    args = parser.parse_args()
    debug_mode = args.debug

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
        print("[main] Mode DEBUG  (appuyer sur 'q' pour quitter)")
    else:
        print("[main] Mode ESCAPE  (Ctrl+C pour quitter)")

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

            if card_id and card_id != last_id \
                    and now - cooldown.get(card_id, 0) >= COOLDOWN_SEC:
                card = cards.get(card_id)
                if card:
                    cooldown[card_id] = now
                    last_id = card_id
                    on_detect(card, sock, udp_port, debug_reader)
            elif not card_id:
                last_id = None

            if debug_mode:
                cam_panel = cv2.resize(draw_cam_overlay(frame, result, idle_text), (HALF, DEBUG_H))
                vid_frame = debug_reader.read() if debug_reader else None
                vid_panel = cv2.resize(vid_frame, (HALF, DEBUG_H)) if vid_frame is not None \
                            else make_black_panel(HALF, DEBUG_H, "En attente vid\u00e9o...")
                cv2.imshow("S.T.E.A.M Vision", np.hstack([cam_panel, vid_panel]))
                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    print("[main] Quitter demand\u00e9.")
                    break

    except KeyboardInterrupt:
        print("[main] Arr\u00eat.")
    finally:
        pipe.stop()
        cam.stop()
        if debug_reader:
            debug_reader.stop()
        cv2.destroyAllWindows()
        os._exit(0)  # kill propre tous les threads


if __name__ == "__main__":
    main()
