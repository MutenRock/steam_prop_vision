"""
steamcore/assets.py
Gestionnaire centralise des assets (audio, img, video).

Structure :
  assets/
    audio/          -> .mp3 .wav .ogg ...
    img/            -> .jpg .png .gif ...
    video/          -> .mp4 .mkv .avi ...

Sous-dossiers supportes (ex: assets/audio/ambiance/, assets/video/success/)
"""
from __future__ import annotations
import random
from pathlib import Path

AUDIO_EXT = {".mp3", ".wav", ".ogg", ".flac", ".aac", ".m4a"}
IMAGE_EXT  = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
VIDEO_EXT  = {".mp4", ".mkv", ".avi", ".mov", ".webm"}


class AssetLibrary:
    def __init__(self, root: str = "assets"):
        self.root  = Path(root)
        self.audio = Path(root) / "audio"
        self.img   = Path(root) / "img"
        self.video = Path(root) / "video"

    def list_audio(self, subdir: str = "") -> list[Path]:
        return self._list(self.audio / subdir if subdir else self.audio, AUDIO_EXT)

    def list_img(self, subdir: str = "") -> list[Path]:
        return self._list(self.img / subdir if subdir else self.img, IMAGE_EXT)

    def list_video(self, subdir: str = "") -> list[Path]:
        return self._list(self.video / subdir if subdir else self.video, VIDEO_EXT)

    def random_audio(self, subdir: str = "") -> Path | None:
        return self._pick(self.list_audio(subdir))

    def random_img(self, subdir: str = "") -> Path | None:
        return self._pick(self.list_img(subdir))

    def random_video(self, subdir: str = "") -> Path | None:
        return self._pick(self.list_video(subdir))

    def get(self, category: str, filename: str) -> Path | None:
        path = getattr(self, category, self.root / category) / filename
        return path if path.exists() else None

    def summary(self) -> str:
        a = len(self.list_audio())
        i = len(self.list_img())
        v = len(self.list_video())
        return f"assets: {a} audio  {i} img  {v} video"

    @staticmethod
    def _list(folder: Path, exts: set) -> list[Path]:
        if not folder.exists():
            return []
        return sorted(p for p in folder.rglob("*")
                      if p.is_file() and p.suffix.lower() in exts)

    @staticmethod
    def _pick(files: list[Path]) -> Path | None:
        return random.choice(files) if files else None
