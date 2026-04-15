"""
apps/video_player.py
Player vidéo mpv piloté via socket IPC.
- Frame 1 en pause au démarrage (idle)
- Lance la vidéo quand carte détectée
- Retour frame 1 à la fin
- Rotation aléatoire si plusieurs fichiers dans le dossier

Usage standalone:
    python3 apps/video_player.py --card vampire
    python3 apps/video_player.py --card vampire --video-dir assets/video

Intégration pipeline:
    from apps.video_player import VideoPlayer
    player = VideoPlayer()
    player.start()
    player.play_card("vampire")   # déclenché par pipeline
    player.stop()
"""
from __future__ import annotations
import os, json, socket, time, subprocess, random, argparse, threading, glob

VIDEO_DIR  = os.path.join(os.path.dirname(__file__), "..", "assets", "video")
MPV_SOCKET = "/tmp/steam_mpv.sock"
MPV_BIN    = "mpv"


def _find_videos(card_name: str, video_dir: str = VIDEO_DIR) -> list[str]:
    """Retourne la liste des mp4 dans le dossier de la carte."""
    card_dir = os.path.join(video_dir, card_name.replace("plate_", ""))
    if not os.path.isdir(card_dir):
        print("[player] dossier introuvable : " + card_dir)
        return []
    return sorted(glob.glob(os.path.join(card_dir, "*.mp4")))


class VideoPlayer:
    """
    Contrôle mpv via socket IPC.
    mpv tourne en fullscreen, on lui envoie des commandes JSON.
    """

    def __init__(
        self,
        video_dir:  str  = VIDEO_DIR,
        mpv_socket: str  = MPV_SOCKET,
        fullscreen: bool = True,
    ):
        self.video_dir  = video_dir
        self.mpv_socket = mpv_socket
        self.fullscreen = fullscreen
        self._proc: subprocess.Popen | None = None

    def start(self, initial_card: str | None = None):
        """
        Lance mpv en pause sur la première frame.
        Si initial_card est fourni, charge le premier fichier de cette carte.
        """
        vids = _find_videos(initial_card or "", self.video_dir) if initial_card else []
        cmd  = [
            MPV_BIN,
            "--input-ipc-server=" + self.mpv_socket,
            "--keep-open=yes",
            "--pause",
            "--loop=no",
        ]
        if self.fullscreen:
            cmd.append("--fullscreen")
        if vids:
            cmd.append(vids[0])
        else:
            cmd.append("--idle=yes")

        self._proc = subprocess.Popen(cmd,
                                      stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL)
        time.sleep(1.5)
        print("[player] mpv démarré (socket=" + self.mpv_socket + ")")

    def play_card(self, card_id: str):
        """
        Déclenché par le pipeline quand une carte est confirmée.
        Charge une vidéo aléatoire de la carte et la lance.
        """
        vids = _find_videos(card_id, self.video_dir)
        if not vids:
            print("[player] aucune vidéo pour " + card_id)
            return
        chosen = random.choice(vids)
        print("[player] play " + os.path.basename(chosen) + " (" + card_id + ")")
        self._send(["loadfile", chosen, "replace"])
        time.sleep(0.3)
        self._send(["set_property", "pause", False])

    def pause_on_frame1(self):
        """Retour à la première frame en pause (état idle)."""
        self._send(["seek", 0, "absolute"])
        self._send(["set_property", "pause", True])
        print("[player] idle — frame 1 pause")

    def stop(self):
        """Quitter mpv proprement."""
        self._send(["quit"])
        if self._proc:
            try:    self._proc.wait(timeout=3)
            except: self._proc.kill()
        print("[player] stopped")

    def watch_end(self, on_end_callback):
        """Thread qui surveille la fin de vidéo et appelle le callback."""
        def _loop():
            while self._proc and self._proc.poll() is None:
                try:
                    if self._get_property("eof-reached"):
                        on_end_callback()
                        time.sleep(1.0)
                except Exception:
                    pass
                time.sleep(0.5)
        threading.Thread(target=_loop, daemon=True, name="mpv-watch").start()

    # ── IPC ──────────────────────────────────────────────────────────────────────────

    def _send(self, cmd: list):
        msg = json.dumps({"command": cmd}).encode() + b"\n"
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(2.0)
                s.connect(self.mpv_socket)
                s.sendall(msg)
        except Exception as e:
            print("[player] IPC error : " + str(e))

    def _get_property(self, prop: str):
        msg = json.dumps({"command": ["get_property", prop]}).encode() + b"\n"
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(2.0)
                s.connect(self.mpv_socket)
                s.sendall(msg)
                data = s.recv(4096).decode()
                r = json.loads(data.strip().split("\n")[0])
                return r.get("data")
        except Exception:
            return None


# ── Standalone test ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--card",      default="vampire")
    p.add_argument("--video-dir", default=VIDEO_DIR)
    args = p.parse_args()

    player = VideoPlayer(video_dir=args.video_dir)
    player.start(initial_card=args.card)
    player.watch_end(player.pause_on_frame1)
    player.play_card(args.card)

    try:
        print("[test] Ctrl+C pour quitter")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass

    player.stop()
