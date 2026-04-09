"""
steamcore/recognition/fast_detector.py
Niveau 1 -- detection rapide de losange/quadrilatere par contours OpenCV.
Retourne une ROI dynamique autour du quad detecte.
Tourne sur le thread principal, vise 20-30fps sur Pi 5.
"""
from __future__ import annotations
from dataclasses import dataclass
import cv2
import numpy as np


@dataclass
class QuadROI:
    x: int
    y: int
    w: int
    h: int
    corners: np.ndarray   # (4,2) float32
    confidence: float     # 0..1 basee sur la regularite du quad

    def to_slice(self):
        return slice(self.y, self.y + self.h), slice(self.x, self.x + self.w)

    def crop(self, frame: np.ndarray) -> np.ndarray:
        return frame[self.to_slice()]


class FastDetector:
    """
    Detecte un quadrilatere (plaque losange format predefini) dans une frame.
    Parametres ajustables via config.json -> fast_detector.
    """

    def __init__(
        self,
        min_area:      int   = 4000,
        max_area_ratio: float = 0.35,
        approx_eps:    float = 0.04,
        margin:        int   = 30,
        blur_k:        int   = 5,
        canny_lo:      int   = 40,
        canny_hi:      int   = 120,
    ):
        self.min_area       = min_area
        self.max_area_ratio = max_area_ratio
        self.approx_eps     = approx_eps
        self.margin         = margin
        self.blur_k         = blur_k | 1   # doit etre impair
        self.canny_lo       = canny_lo
        self.canny_hi       = canny_hi

    def load_config(self, cfg: dict):
        fd = cfg.get("fast_detector", {})
        self.min_area       = fd.get("min_area",        self.min_area)
        self.max_area_ratio = fd.get("max_area_ratio",  self.max_area_ratio)
        self.approx_eps     = fd.get("approx_eps",      self.approx_eps)
        self.margin         = fd.get("margin",          self.margin)
        self.blur_k         = fd.get("blur_k",          self.blur_k) | 1
        self.canny_lo       = fd.get("canny_lo",        self.canny_lo)
        self.canny_hi       = fd.get("canny_hi",        self.canny_hi)

    def detect(self, frame: np.ndarray) -> QuadROI | None:
        h, w = frame.shape[:2]
        max_area = w * h * self.max_area_ratio

        gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blur  = cv2.GaussianBlur(gray, (self.blur_k, self.blur_k), 0)
        edges = cv2.Canny(blur, self.canny_lo, self.canny_hi)
        cnts, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)

        best: QuadROI | None = None
        best_score = 0.0

        for cnt in cnts:
            area = cv2.contourArea(cnt)
            if area < self.min_area or area > max_area:
                continue
            peri   = cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, self.approx_eps * peri, True)
            if len(approx) != 4:
                continue
            if not cv2.isContourConvex(approx):
                continue

            corners = approx.reshape(4, 2).astype(np.float32)
            score   = self._regularity_score(corners, area)
            if score > best_score:
                best_score = score
                rx, ry, rw, rh = cv2.boundingRect(approx)
                # ajouter marge en restant dans la frame
                mx = self.margin
                rx = max(0, rx - mx)
                ry = max(0, ry - mx)
                rw = min(w - rx, rw + 2 * mx)
                rh = min(h - ry, rh + 2 * mx)
                best = QuadROI(x=rx, y=ry, w=rw, h=rh,
                               corners=corners, confidence=score)

        return best

    @staticmethod
    def _regularity_score(corners: np.ndarray, area: float) -> float:
        """Score 0..1 : plus le quad est regulier (losange/carre), plus c'est haut."""
        sides = []
        for i in range(4):
            d = np.linalg.norm(corners[i] - corners[(i+1) % 4])
            sides.append(d)
        mean_s = np.mean(sides)
        if mean_s < 1e-5:
            return 0.0
        std_s  = np.std(sides)
        return float(np.clip(1.0 - std_s / mean_s, 0.0, 1.0))
