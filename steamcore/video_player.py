"""
steamcore/video_player.py
Lecture vidéo fullscreen sur sortie HDMI de STYX.
Utilise mpv (préféré) ou ffplay en fallback.

Installation : sudo apt install mpv
"""
from __future__ import annotations
import subprocess
import threading
import shutil
import random
from pathlib import Path

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".webm"}


class VideoPlayer:
    def __init__(self, assets_dir: str = "assets/video"):
        self.assets_dir = Path(assets_dir)
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._player = self._detect_player()

    @staticmethod
    def _detect_player() -> str:
        for p in ("mpv", "ffplay", "vlc"):
            if shutil.which(p):
                return p
        print("[video] WARN: aucun lecteur trouvé (mpv/ffplay/vlc)")
        return "mpv"

    # ── API publique ──────────────────────────────────────────────
    def play(self, filepath: str | Path, blocking: bool = False) -> bool:
        path = Path(filepath)
        if not path.is_absolute() and not path.exists():
            path = self.assets_dir / filepath
        if not path.exists():
            print(f"[video] X Fichier introuvable : {path}")
            return False
        self._launch(path, blocking)
        return True

    def play_random(self, subdir: str = "", blocking: bool = False) -> bool:
        folder = self.assets_dir / subdir if subdir else self.assets_dir
        candidates = [
            p for p in folder.rglob("*")
            if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
        ] if folder.exists() else []
        if not candidates:
            print(f"[video] X Aucune vidéo dans : {folder}")
            return False
        chosen = random.choice(candidates)
        self._launch(chosen, blocking)
        return True

    def stop(self):
        with self._lock:
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()
                self._proc = None

    def is_playing(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def list_files(self, subdir: str = "") -> list[Path]:
        folder = self.assets_dir / subdir if subdir else self.assets_dir
        if not folder.exists():
            return []
        return sorted(p for p in folder.rglob("*")
                      if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS)

    # ── Interne ───────────────────────────────────────────────────
    def _launch(self, path: Path, blocking: bool):
        import os
        self.stop()
        cmd = self._build_cmd(path)
        env = {**os.environ, "DISPLAY": ":0"}
        with self._lock:
            self._proc = subprocess.Popen(cmd, env=env,
                                          stdout=subprocess.DEVNULL,
                                          stderr=subprocess.DEVNULL)
            proc = self._proc   # référence locale (race condition safe)
        print(f"[video] >> {path.name}  (via {self._player})")
        if blocking:
            proc.wait()

    def _build_cmd(self, path: Path) -> list[str]:
        if self._player == "mpv":
            return [
                "mpv",
                "--fullscreen",
                "--no-terminal",
                "--really-quiet",
                "--no-audio",          # audio géré séparément par AudioPlayer
                str(path),
            ]
        elif self._player == "ffplay":
            return [
                "ffplay",
                "-fs",
                "-autoexit",
                "-an",                 # no audio
                "-loglevel", "quiet",
                str(path),
            ]
        else:  # vlc
            return [
                "vlc",
                "--fullscreen",
                "--intf", "dummy",
                "--play-and-exit",
                "--no-audio",          # audio géré séparément par AudioPlayer
                str(path),
            ]
