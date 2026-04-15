"""
apps/video_player.py  v2
Player vidéo mpv piloté via socket IPC.

Comportement :
  - Au démarrage : fenêtre noire fullscreen avec titre (idle screen via OpenCV)
  - Carte détectée : mpv lance la vidéo en fullscreen
  - Fin de vidéo  : retour à l'idle screen

Usage standalone:
    python3 apps/video_player.py --card vampire

Intégration pipeline:
    from apps.video_player import VideoPlayer
    player = VideoPlayer()
    player.start()
    player.play_card("plate_vampire")
    player.stop()
"""
from __future__ import annotations
import os, json, socket, time, subprocess, random, argparse, threading, glob

import cv2
import numpy as np

VIDEO_DIR    = os.path.join(os.path.dirname(__file__), "..", "assets", "video")
MPV_SOCKET   = "/tmp/steam_mpv.sock"
MPV_BIN      = "mpv"
IDLE_WIN     = "steam_vision"
IDLE_TITLE   = "Qui ose se presenter devant moi ?\nQu'avez-vous a m'offrir ?"
FONT         = cv2.FONT_HERSHEY_SIMPLEX


def _find_videos(card_name: str, video_dir: str = VIDEO_DIR) -> list[str]:
    card_dir = os.path.join(video_dir, card_name.replace("plate_", ""))
    if not os.path.isdir(card_dir):
        return []
    return sorted(glob.glob(os.path.join(card_dir, "*.mp4")))


def _make_idle_frame(w: int = 1280, h: int = 720) -> np.ndarray:
    """Génère une frame noire avec le texte idle centré."""
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    lines = IDLE_TITLE.split("\n")
    scale  = 1.1
    thick  = 2
    line_h = int(cv2.getTextSize("A", FONT, scale, thick)[0][1] * 2.8)
    total_h = line_h * len(lines)
    y_start = (h - total_h) // 2 + line_h
    for i, line in enumerate(lines):
        tw = cv2.getTextSize(line, FONT, scale, thick)[0][0]
        x  = (w - tw) // 2
        y  = y_start + i * line_h
        # ombre
        cv2.putText(frame, line, (x + 2, y + 2), FONT, scale, (80, 40, 0), thick + 2)
        # texte doré
        cv2.putText(frame, line, (x, y), FONT, scale, (0, 180, 220), thick)
    return frame


class VideoPlayer:
    """
    Gère l'idle screen OpenCV + le player mpv pour les vidéos plein écran.
    """

    def __init__(
        self,
        video_dir:  str  = VIDEO_DIR,
        mpv_socket: str  = MPV_SOCKET,
        win_w:      int  = 1280,
        win_h:      int  = 720,
    ):
        self.video_dir  = video_dir
        self.mpv_socket = mpv_socket
        self.win_w      = win_w
        self.win_h      = win_h
        self._proc:      subprocess.Popen | None = None
        self._idle_frame = _make_idle_frame(win_w, win_h)
        self._playing    = False
        self._idle_thread: threading.Thread | None = None
        self._running    = False

    # ── Cycle de vie ────────────────────────────────────────────────────

    def start(self):
        """Ouvre la fenêtre idle fullscreen."""
        self._running = True
        cv2.namedWindow(IDLE_WIN, cv2.WINDOW_NORMAL)
        cv2.setWindowProperty(IDLE_WIN, cv2.WND_PROP_FULLSCREEN,
                              cv2.WINDOW_FULLSCREEN)
        self._show_idle()
        self._idle_thread = threading.Thread(
            target=self._idle_loop, daemon=True, name="idle-loop")
        self._idle_thread.start()
        print("[player] idle screen actif")

    def stop(self):
        """Ferme tout."""
        self._running = False
        self._kill_mpv()
        cv2.destroyWindow(IDLE_WIN)
        print("[player] stopped")

    # ── Contrôle ───────────────────────────────────────────────────────

    def play_card(self, card_id: str):
        """Lance la vidéo de la carte en fullscreen, cache l'idle screen."""
        vids = _find_videos(card_id, self.video_dir)
        if not vids:
            print("[player] aucune vidéo pour " + card_id)
            return
        chosen = random.choice(vids)
        print("[player] play " + os.path.basename(chosen))

        # Cacher la fenêtre idle
        cv2.setWindowProperty(IDLE_WIN, cv2.WND_PROP_VISIBLE, 0)
        self._playing = True

        # Lancer mpv en fullscreen
        self._kill_mpv()
        cmd = [
            MPV_BIN,
            "--fullscreen",
            "--no-osd-bar",
            "--input-ipc-server=" + self.mpv_socket,
            "--keep-open=no",
            chosen,
        ]
        self._proc = subprocess.Popen(cmd,
                                      stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL)
        # Thread de surveillance fin de vidéo
        threading.Thread(target=self._watch_end, daemon=True,
                         name="mpv-watch").start()

    def _watch_end(self):
        """Attend que mpv se termine, puis reaffiche l'idle screen."""
        if self._proc:
            self._proc.wait()
        self._playing = False
        self._show_idle()
        print("[player] video terminée, retour idle")

    def _show_idle(self):
        """Réaffiche la fenêtre idle."""
        cv2.setWindowProperty(IDLE_WIN, cv2.WND_PROP_VISIBLE, 1)
        cv2.setWindowProperty(IDLE_WIN, cv2.WND_PROP_FULLSCREEN,
                              cv2.WINDOW_FULLSCREEN)
        cv2.imshow(IDLE_WIN, self._idle_frame)
        cv2.waitKey(1)

    def _idle_loop(self):
        """Maintient la fenêtre idle vivante (waitKey requis par Qt)."""
        while self._running:
            if not self._playing:
                cv2.waitKey(100)
            else:
                time.sleep(0.1)

    def _kill_mpv(self):
        if self._proc and self._proc.poll() is None:
            try:
                self._send(["quit"])
                self._proc.wait(timeout=2)
            except Exception:
                self._proc.kill()
            self._proc = None

    # ── IPC mpv ───────────────────────────────────────────────────────

    def _send(self, cmd: list):
        msg = json.dumps({"command": cmd}).encode() + b"\n"
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(2.0)
                s.connect(self.mpv_socket)
                s.sendall(msg)
        except Exception:
            pass


# ── Standalone test ─────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--card",      default="vampire")
    p.add_argument("--video-dir", default=VIDEO_DIR)
    args = p.parse_args()

    player = VideoPlayer(video_dir=args.video_dir)
    player.start()

    print("[test] lecture dans 3s : " + args.card)
    time.sleep(3)
    player.play_card(args.card)

    try:
        print("[test] Ctrl+C pour quitter")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass

    player.stop()


if __name__ == "__main__":
    main()
