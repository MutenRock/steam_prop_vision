"""
steamcore/audio.py
Joue un fichier audio via ffplay (non-bloquant).
- play(filename)      : joue un fichier precis
- play_random()       : pioche aleatoirement dans assets/audio/
- play_random(subdir) : pioche dans assets/audio/<subdir>/
"""
from __future__ import annotations
import subprocess
import threading
import shutil
import random
from pathlib import Path

AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".flac", ".aac", ".m4a"}


class AudioPlayer:
    def __init__(self, assets_dir: str = "assets/audio"):
        self.assets_dir = Path(assets_dir)
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._ffplay = shutil.which("ffplay") or "ffplay"

    def play(self, filename: str, blocking: bool = False) -> bool:
        path = Path(filename)
        if not path.is_absolute() and not path.exists():
            path = self.assets_dir / filename
        if not path.exists():
            print(f"[audio] X Fichier introuvable : {path}")
            return False
        self._launch(path, blocking)
        return True

    def play_random(self, subdir: str = "", blocking: bool = False) -> bool:
        folder = self.assets_dir / subdir if subdir else self.assets_dir
        candidates = [
            p for p in folder.iterdir()
            if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS
        ] if folder.exists() else []
        if not candidates:
            print(f"[audio] X Aucun fichier audio dans : {folder}")
            return False
        self._launch(random.choice(candidates), blocking)
        return True

    def list_files(self, subdir: str = "") -> list[Path]:
        folder = self.assets_dir / subdir if subdir else self.assets_dir
        if not folder.exists():
            return []
        return [p for p in sorted(folder.iterdir())
                if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS]

    def stop(self):
        with self._lock:
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()
                self._proc = None

    def is_playing(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def _launch(self, path: Path, blocking: bool):
        self.stop()
        cmd = [self._ffplay, "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)]
        with self._lock:
            self._proc = subprocess.Popen(cmd)
        print(f"[audio] >> {path.name}")
        if blocking:
            self._proc.wait()
