"""
apps/video_player.py  v3
Player vidéo mpv piloté via socket IPC.

Règle OpenCV : namedWindow / imshow / waitKey DOIVENT être appelés
depuis le thread principal. VideoPlayer n'a donc plus de thread interne
pour l'idle screen : c'est la boucle principale (plate_bench) qui appelle
player.tick() à chaque itération.

Comportement :
  - Au démarrage    : fenêtre noire fullscreen + titre (idle screen)
  - Carte détectée : mpv lance la vidéo en fullscreen, idle cachée
  - Fin de vidéo   : retour à l'idle screen

Intégration pipeline :
    player = VideoPlayer()
    player.start()              # thread principal
    # dans la boucle :
    player.tick()               # thread principal - maintient la fenêtre
    player.play_card(card_id)   # déclenché sur détection
    # à la fin :
    player.stop()               # thread principal

Usage standalone :
    python3 apps/video_player.py --card vampire
"""
from __future__ import annotations
import os, json, socket, time, subprocess, random, argparse, threading, glob

import cv2
import numpy as np

VIDEO_DIR  = os.path.join(os.path.dirname(__file__), "..", "assets", "video")
MPV_SOCKET = "/tmp/steam_mpv.sock"
MPV_BIN    = "mpv"
IDLE_WIN   = "steam_vision"
IDLE_TITLE = "Qui ose se presenter devant moi ?\nQu'avez-vous a m'offrir ?"
FONT       = cv2.FONT_HERSHEY_SIMPLEX


def _find_videos(card_name: str, video_dir: str = VIDEO_DIR) -> list[str]:
    card_dir = os.path.join(video_dir, card_name.replace("plate_", ""))
    if not os.path.isdir(card_dir):
        return []
    return sorted(glob.glob(os.path.join(card_dir, "*.mp4")))


def _make_idle_frame(w: int = 1280, h: int = 720) -> np.ndarray:
    frame  = np.zeros((h, w, 3), dtype=np.uint8)
    lines  = IDLE_TITLE.split("\n")
    scale  = 1.1
    thick  = 2
    line_h = int(cv2.getTextSize("A", FONT, scale, thick)[0][1] * 2.8)
    y0     = (h - line_h * len(lines)) // 2 + line_h
    for i, line in enumerate(lines):
        tw = cv2.getTextSize(line, FONT, scale, thick)[0][0]
        x  = (w - tw) // 2
        y  = y0 + i * line_h
        cv2.putText(frame, line, (x + 2, y + 2), FONT, scale, (80, 40, 0),   thick + 2)
        cv2.putText(frame, line, (x,     y),     FONT, scale, (0, 180, 220), thick)
    return frame


class VideoPlayer:
    """
    Idle screen OpenCV (thread principal) + player mpv (subprocess).
    Appeler tick() à chaque frame depuis le thread principal.
    """

    def __init__(
        self,
        video_dir:  str = VIDEO_DIR,
        mpv_socket: str = MPV_SOCKET,
        win_w:      int = 1280,
        win_h:      int = 720,
    ):
        self.video_dir   = video_dir
        self.mpv_socket  = mpv_socket
        self._idle_frame = _make_idle_frame(win_w, win_h)
        self._proc: subprocess.Popen | None = None
        self._playing    = False
        self._running    = False
        self._show_req   = False   # signal thread -> thread principal

    # ── Cycle de vie (thread principal) ────────────────────────────────

    def start(self):
        """Crée la fenêtre idle fullscreen (appeler depuis le thread principal)."""
        self._running = True
        cv2.namedWindow(IDLE_WIN, cv2.WINDOW_NORMAL)
        cv2.setWindowProperty(IDLE_WIN, cv2.WND_PROP_FULLSCREEN,
                              cv2.WINDOW_FULLSCREEN)
        cv2.imshow(IDLE_WIN, self._idle_frame)
        cv2.waitKey(1)
        print("[player] idle screen actif")

    def tick(self):
        """
        A appeler à chaque itération de la boucle principale.
        Maintient la fenêtre idle vivante et gère le retour après vidéo.
        """
        if not self._running:
            return
        # Le thread _watch_end signale qu'on doit réafficher l'idle
        if self._show_req:
            self._show_req = False
            cv2.setWindowProperty(IDLE_WIN, cv2.WND_PROP_FULLSCREEN,
                                  cv2.WINDOW_FULLSCREEN)
            cv2.imshow(IDLE_WIN, self._idle_frame)
        cv2.waitKey(1)

    def stop(self):
        """Ferme tout (appeler depuis le thread principal)."""
        self._running = False
        self._kill_mpv()
        try:
            cv2.destroyWindow(IDLE_WIN)
        except Exception:
            pass
        print("[player] stopped")

    # ── Contrôle ────────────────────────────────────────────────────

    def play_card(self, card_id: str):
        """Lance la vidéo de la carte (peut être appelé depuis n'importe quel thread)."""
        vids = _find_videos(card_id, self.video_dir)
        if not vids:
            print("[player] aucune vidéo pour " + card_id)
            return
        chosen = random.choice(vids)
        print("[player] play " + os.path.basename(chosen))
        self._playing = True
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
        threading.Thread(target=self._watch_end, daemon=True,
                         name="mpv-watch").start()

    @property
    def is_playing(self) -> bool:
        return self._playing

    # ── Interne ──────────────────────────────────────────────────────

    def _watch_end(self):
        """Thread : attend la fin de mpv et signale le retour idle."""
        if self._proc:
            self._proc.wait()
        self._playing  = False
        self._show_req = True   # sera traité par tick() dans le thread principal
        print("[player] video terminée, retour idle")

    def _kill_mpv(self):
        if self._proc and self._proc.poll() is None:
            try:
                self._send(["quit"])
                self._proc.wait(timeout=2)
            except Exception:
                self._proc.kill()
        self._proc = None

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

    deadline = time.time() + 3.0
    print("[test] lecture dans 3s : " + args.card)
    while time.time() < deadline:
        player.tick()
        time.sleep(0.03)

    player.play_card(args.card)

    print("[test] Ctrl+C pour quitter")
    try:
        while True:
            player.tick()
            time.sleep(0.03)
    except KeyboardInterrupt:
        pass

    player.stop()


if __name__ == "__main__":
    main()
