"""
steamcore/recognition/card_recognizer.py
Reconnaissance ORB par quadrants : valide si >= min_quadrants sur 4 matchent.
"""
from __future__ import annotations
from pathlib import Path
from dataclasses import dataclass, field
import cv2
import numpy as np


def _find_images(directory: Path) -> list:
    exts = ["*.jpg", "*.jpeg", "*.png", "*.JPG", "*.JPEG", "*.PNG", "*.webp"]
    imgs = []
    for ext in exts:
        imgs.extend(directory.rglob(ext))
    return [p for p in imgs if not p.name.startswith(".")]


# Quadrants : (y1, y2, x1, x2) en fractions du warp
_QUADS = [
    (0,   0.5, 0,   0.5),   # top-left
    (0,   0.5, 0.5, 1.0),   # top-right
    (0.5, 1.0, 0,   0.5),   # bottom-left
    (0.5, 1.0, 0.5, 1.0),   # bottom-right
]


@dataclass
class RecognitionResult:
    card_id:    str
    label:      str
    score:      float
    matches:    int
    quads_ok:   int = 0   # nb de quadrants valides


class CardRecognizer:
    WARP_SIZE  = 400
    RATIO_TEST = 0.75

    def __init__(
        self,
        platest_dir:    str   = "PLATEST",
        # parametres globaux (fallback si pas de config quadrant)
        min_matches:    int   = 8,
        threshold:      float = 0.04,
        # parametres quadrants
        quad_min_matches: int   = 4,
        quad_threshold:   float = 0.03,
        min_quadrants:    int   = 2,
    ):
        self.platest_dir      = platest_dir
        self.min_matches      = min_matches
        self.threshold        = threshold
        self.quad_min_matches = quad_min_matches
        self.quad_threshold   = quad_threshold
        self.min_quadrants    = min_quadrants
        self._orb     = cv2.ORB_create(nfeatures=800)
        self._matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
        self._templates: list = []
        self._load()

    def load_config(self, cfg: dict):
        cr = cfg.get("detection", {})
        self.quad_min_matches = cr.get("quad_min_matches", self.quad_min_matches)
        self.quad_threshold   = cr.get("quad_threshold",   self.quad_threshold)
        self.min_quadrants    = cr.get("min_quadrants",    self.min_quadrants)
        self.reload()

    def recognize(self, warped: np.ndarray, hint_id: str | None = None):
        gray = self._to_gray(warped)
        gray = cv2.resize(gray, (self.WARP_SIZE, self.WARP_SIZE))
        S    = self.WARP_SIZE

        templates = self._templates
        if hint_id:
            templates = [t for t in self._templates if t.card_id == hint_id] or self._templates

        best_score, best_quads, best_id = 0.0, 0, None

        for tmpl in templates:
            quads_ok = 0
            total_score = 0.0

            for (fy1, fy2, fx1, fx2) in _QUADS:
                y1, y2 = int(fy1 * S), int(fy2 * S)
                x1, x2 = int(fx1 * S), int(fx2 * S)
                patch = gray[y1:y2, x1:x2]

                kps_q, desc_q = self._orb.detectAndCompute(patch, None)
                if desc_q is None:
                    continue

                score, matches = self._score_quad(kps_q, desc_q, tmpl,
                                                   fy1, fy2, fx1, fx2)
                total_score += score
                if score >= self.quad_threshold and matches >= self.quad_min_matches:
                    quads_ok += 1

            if quads_ok > best_quads or (
                    quads_ok == best_quads and total_score > best_score):
                best_quads = quads_ok
                best_score = total_score
                best_id    = tmpl.card_id

        if best_id is None or best_quads < self.min_quadrants:
            return None

        label = best_id.replace("plate_", "").replace("_", " ").capitalize()
        return RecognitionResult(
            card_id=best_id, label=label,
            score=round(best_score, 4), matches=0,
            quads_ok=best_quads,
        )

    def reload(self):
        self._templates.clear()
        self._load()

    @property
    def card_ids(self) -> list:
        return [t.card_id for t in self._templates]

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
            if tmpl.quad_descs:
                self._templates.append(tmpl)
        print("[recognizer] " + str(len(self._templates)) + " cartes chargees")

    def _score_quad(self, kps_q, desc_q, tmpl, fy1, fy2, fx1, fx2):
        """Score ORB sur le patch de quadrant correspondant du template."""
        key = (fy1, fy2, fx1, fx2)
        quad_data = tmpl.quad_descs.get(key)
        if not quad_data:
            return 0.0, 0
        top_score, top_matches = 0.0, 0
        for kps_r, desc_r in quad_data:
            try:
                ms   = self._matcher.knnMatch(desc_q, desc_r, k=2)
                good = [m for m, n in ms
                        if m.distance < self.RATIO_TEST * n.distance]
                s    = len(good) / max(len(kps_r), len(kps_q), 1)
                if s > top_score:
                    top_score, top_matches = s, len(good)
            except Exception:
                continue
        return top_score, top_matches

    @staticmethod
    def _to_gray(img: np.ndarray) -> np.ndarray:
        return img if len(img.shape) == 2 \
            else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


class _OrbTemplate:
    """Stocke les descripteurs ORB par quadrant pour chaque image template."""
    def __init__(self, card_id: str, paths, orb):
        self.card_id   = card_id
        self.quad_descs: dict = {}   # {(fy1,fy2,fx1,fx2): [(kps, desc), ...]}

        for (fy1, fy2, fx1, fx2) in _QUADS:
            self.quad_descs[(fy1, fy2, fx1, fx2)] = []

        S = CardRecognizer.WARP_SIZE
        for p in paths:
            img = cv2.imread(str(p))
            if img is None:
                continue
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            gray = cv2.resize(gray, (S, S))

            for (fy1, fy2, fx1, fx2) in _QUADS:
                y1, y2 = int(fy1 * S), int(fy2 * S)
                x1, x2 = int(fx1 * S), int(fx2 * S)
                patch  = gray[y1:y2, x1:x2]
                kps, desc = orb.detectAndCompute(patch, None)
                if desc is not None and len(kps) >= 3:
                    self.quad_descs[(fy1, fy2, fx1, fx2)].append((kps, desc))
