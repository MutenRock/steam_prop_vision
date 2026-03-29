# -*- coding: utf-8 -*-
"""
Plaque recognition from reference images in config folder.

Baseline: ORB feature matching (no training).
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import os

try:
    import cv2  # type: ignore
except Exception:
    cv2 = None


@dataclass
class PlaqueMatch:
    plaque_id: str
    score: float
    good_matches: int
    detail: str = ""


class PlaqueRecognizer:
    def __init__(self):
        self.enabled = True
        self.min_good_matches = 18
        self.ratio_test = 0.75

        self._orb = None
        self._bf = None
        self._refs: Dict[str, Tuple[object, object]] = {}

    def is_available(self) -> bool:
        return cv2 is not None

    def load_from_folder(self, plaques_folder: str) -> List[str]:
        self._refs.clear()
        if cv2 is None:
            return []
        self._orb = cv2.ORB_create(nfeatures=1200)
        self._bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)

        loaded = []
        for fn in sorted(os.listdir(plaques_folder)):
            if not fn.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".webp")):
                continue
            pid = os.path.splitext(fn)[0]
            path = os.path.join(plaques_folder, fn)
            img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue
            kp, des = self._orb.detectAndCompute(img, None)
            if des is None or len(kp) < 10:
                continue
            self._refs[pid] = (kp, des)
            loaded.append(pid)
        return loaded

    def recognize(self, frame_bgr) -> Optional[PlaqueMatch]:
        if not self.enabled or cv2 is None or self._orb is None or self._bf is None:
            return None
        if not self._refs:
            return None

        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        kp_f, des_f = self._orb.detectAndCompute(gray, None)
        if des_f is None or len(kp_f) < 20:
            return None

        best = None
        for pid, (_, des_r) in self._refs.items():
            try:
                matches = self._bf.knnMatch(des_r, des_f, k=2)
            except Exception:
                continue
            good = 0
            for m_n in matches:
                if len(m_n) < 2:
                    continue
                m, n = m_n[0], m_n[1]
                if m.distance < self.ratio_test * n.distance:
                    good += 1
            if good <= 0:
                continue
            score = min(1.0, good / 60.0)
            if best is None or good > best.good_matches:
                best = PlaqueMatch(pid, float(score), int(good), detail=f"good_matches={good}")
        if best and best.good_matches >= self.min_good_matches:
            return best
        return None
