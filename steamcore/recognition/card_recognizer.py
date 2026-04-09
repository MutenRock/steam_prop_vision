"""
steamcore/recognition/card_recognizer.py
v2 -- Confirmation ORB sur warp 400x400.
"""
from __future__ import annotations
from pathlib import Path
from dataclasses import dataclass

import cv2
import numpy as np


def _find_images(directory: Path) -> list[Path]:
    exts = ["*.jpg", "*.jpeg", "*.png", "*.JPG", "*.JPEG", "*.PNG", "*.webp"]
    imgs = []
    for ext in exts:
        imgs.extend(directory.glob(ext))
    return imgs


@dataclass
class RecognitionResult:
    card_id:  str
    label:    str
    score:    float
    matches:  int


class CardRecognizer:
    WARP_SIZE  = 400
    RATIO_TEST = 0.75

    def __init__(
        self,
        platest_dir: str   = "PLATEST",
        min_matches: int   = 8,
        threshold:   float = 0.04,
    ):
        self.platest_dir = platest_dir
        self.min_matches = min_matches
        self.threshold   = threshold
        self._orb        = cv2.ORB_create(nfeatures=800)
        self._matcher    = cv2.BFMatcher(cv2.NORM_HAMMING)
        self._templates: list[_OrbTemplate] = []
        self._load()

    # ── public ──────────────────────────────────────────────

    def recognize(self, warped: np.ndarray, hint_id: str | None = None):
        gray = self._to_gray(warped)
        gray = cv2.resize(gray, (self.WARP_SIZE, self.WARP_SIZE))
        kps_q, desc_q = self._orb.detectAndCompute(gray, None)
        if desc_q is None:
            return None
        templates = self._templates
        if hint_id:
            templates = [t for t in self._templates if t.card_id == hint_id]                         or self._templates
        best_score, best_matches, best_id = 0.0, 0, None
        for tmpl in templates:
            score, matches = self._score(kps_q, desc_q, tmpl)
            if score > best_score:
                best_score, best_matches, best_id = score, matches, tmpl.card_id
        if best_id is None or best_score < self.threshold                 or best_matches < self.min_matches:
            return None
        label = best_id.replace("plate_", "").replace("_", " ").capitalize()
        return RecognitionResult(card_id=best_id, label=label,
                                 score=best_score, matches=best_matches)

    def reload(self):
        self._templates.clear()
        self._load()
        print("[recognizer] " + str(len(self._templates)) + " cartes rechargees")

    @property
    def card_ids(self) -> list[str]:
        return [t.card_id for t in self._templates]   # <-- .card_id partout

    # ── private ─────────────────────────────────────────────

    def _load(self):
        p = Path(self.platest_dir)
        if not p.exists():
            print("[recognizer] PLATEST introuvable : " + str(p))
            return
        for subdir in sorted(p.iterdir()):
            if not subdir.is_dir():
                continue
            imgs = _find_images(subdir)
            if not imgs:
                continue
            tmpl = _OrbTemplate(subdir.name, imgs, self._orb)
            if tmpl.descs:
                self._templates.append(tmpl)
                print("[recognizer] + " + subdir.name +
                      " (" + str(len(tmpl.descs)) + " imgs)")
        print("[recognizer] " + str(len(self._templates)) + " cartes chargees")

    def _score(self, kps_q, desc_q, tmpl):
        top_score, top_matches = 0.0, 0
        for kps_r, desc_r in tmpl.descs:
            try:
                ms   = self._matcher.knnMatch(desc_q, desc_r, k=2)
                good = [m for m, n in ms if m.distance < self.RATIO_TEST * n.distance]
                s    = len(good) / max(len(kps_r), len(kps_q), 1)
                if s > top_score:
                    top_score, top_matches = s, len(good)
            except Exception:
                continue
        return top_score, top_matches

    @staticmethod
    def _to_gray(img: np.ndarray) -> np.ndarray:
        if len(img.shape) == 2:
            return img
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


class _OrbTemplate:
    def __init__(self, card_id: str, paths, orb):
        self.card_id = card_id          # <-- .card_id partout, jamais .id
        self.descs: list[tuple] = []
        for p in paths:
            img = cv2.imread(str(p))
            if img is None:
                continue
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            gray = cv2.resize(gray, (CardRecognizer.WARP_SIZE,
                                     CardRecognizer.WARP_SIZE))
            kps, desc = orb.detectAndCompute(gray, None)
            if desc is not None and len(kps) >= 6:
                self.descs.append((kps, desc))
