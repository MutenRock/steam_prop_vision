"""
steamcore/image_player.py
Affichage d'image fullscreen sur la sortie HDMI du STYX.
Utilise mpv (préféré) ou feh en fallback.

  mpv  : sudo apt install mpv
  feh  : sudo apt install feh
"""
from __future__ import annotations
import os
import subprocess
import threading
import shutil
import random
from pathlib import Path

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif"}


class ImagePlayer:
    def __init__(self, assets_dir: str = "assets/img"):
        self.assets_dir = Path(assets_dir)
        self._proc: subprocess.Popen | None = None
        self._lock   = threading.Lock()
        self._player = self._detect_player()

    @staticmethod
    def _detect_player() -> str:
        for p in ("mpv", "feh", "eog"):
            if shutil.which(p):
                return p
        print("[image] WARN: aucun lecteur image trouvé (mpv/feh/eog)")
        return "mpv"

    # ── API publique ──────────────────────────────────────────────
    def show(self, filepath: str | Path, blocking: bool = False) -> bool:
        path = Path(filepath)
        if not path.is_absolute() and not path.exists():
            path = self.assets_dir / filepath
        if not path.exists():
            print(f"[image] X Fichier introuvable : {path}")
            return False
        self._launch(path, blocking)
        return True

    def show_random(self, subdir: str = "", blocking: bool = False) -> bool:
        folder = self.assets_dir / subdir if subdir else self.assets_dir
        candidates = [
            p for p in folder.rglob("*")
            if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
        ] if folder.exists() else []
        if not candidates:
            print(f"[image] X Aucune image dans : {folder}")
            return False
        chosen = random.choice(candidates)
        self._launch(chosen, blocking)
        return True

    def stop(self):
        with self._lock:
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()
                self._proc = None

    def is_showing(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def list_files(self, subdir: str = "") -> list[Path]:
        folder = self.assets_dir / subdir if subdir else self.assets_dir
        if not folder.exists():
            return []
        return sorted(p for p in folder.rglob("*")
                      if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS)

    # ── Interne ───────────────────────────────────────────────────
    def _launch(self, path: Path, blocking: bool):
        self.stop()
        cmd = self._build_cmd(path)
        env = {**os.environ, "DISPLAY": ":0"}
        with self._lock:
            self._proc = subprocess.Popen(cmd, env=env,
                                          stdout=subprocess.DEVNULL,
                                          stderr=subprocess.DEVNULL)
            proc = self._proc
        print(f"[image] >> {path.name}  (via {self._player})")
        if blocking:
            proc.wait()

    def _build_cmd(self, path: Path) -> list[str]:
        if self._player == "mpv":
            return [
                "mpv",
                "--fullscreen",
                "--no-terminal",
                "--really-quiet",
                "--no-audio",
                f"--image-display-duration=inf",
                str(path),
            ]
        elif self._player == "feh":
            return [
                "feh",
                "--fullscreen",
                "--auto-zoom",
                "--hide-pointer",
                str(path),
            ]
        else:  # eog
            return ["eog", "--fullscreen", str(path)]
