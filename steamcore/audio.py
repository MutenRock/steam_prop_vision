"""
steamcore/audio.py
Joue un fichier MP3/WAV via ffplay (déjà installé avec ffmpeg).
Non-bloquant : lance ffplay dans un subprocess séparé.
"""
from __future__ import annotations
import subprocess
import threading
import shutil
from pathlib import Path


class AudioPlayer:
    def __init__(self, assets_dir: str = "assets/audio"):
        self.assets_dir = Path(assets_dir)
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._ffplay = shutil.which("ffplay") or "ffplay"

    def play(self, filename: str, blocking: bool = False) -> bool:
        """
        Joue un fichier audio.
        filename : nom du fichier dans assets_dir (ex: 'success.mp3')
                   ou chemin absolu.
        blocking : attendre la fin de la lecture (défaut False).
        Retourne True si lancé, False si fichier introuvable.
        """
        path = Path(filename)
        if not path.is_absolute():
            path = self.assets_dir / filename

        if not path.exists():
            print(f"[audio] Fichier introuvable : {path}")
            return False

        self.stop()  # stopper l'audio précédent si en cours

        cmd = [
            self._ffplay,
            "-nodisp",          # pas de fenêtre vidéo
            "-autoexit",        # quitter automatiquement à la fin
            "-loglevel", "quiet",
            str(path),
        ]

        with self._lock:
            self._proc = subprocess.Popen(cmd)

        if blocking:
            self._proc.wait()

        print(f"[audio] ▶ {path.name}")
        return True

    def stop(self):
        with self._lock:
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()
                self._proc = None

    def is_playing(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None
