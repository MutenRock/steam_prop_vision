"""
steamcore/recognition/card_detector.py

Détecte un losange (carte diamant) dans une frame et retourne
l'image recadrée + redressée en 400×400.

Algorithme :
  1. CLAHE → améliore le contraste en salle sombre
  2. Canny edge detection
  3. findContours → filtrer les quadrilatères convexes
  4. Valider forme losange (côtés égaux, angles ~90°)
  5. warpPerspective → image normalisée 400×400
"""
from __future__ import annotations
import cv2
import numpy as np
from dataclasses import dataclass


WARP_SIZE = 400   # taille de sortie normalisée


@dataclass
class CardRegion:
    corners: np.ndarray    # 4 points (x,y) dans la frame originale
    warped: np.ndarray     # image 400×400 normalisée
    area: float
    confidence: float      # 0.0→1.0 basé sur la qualité du quadrilatère


class CardDetector:
    def __init__(
        self,
        min_area: int    = 1500,     # px² minimum du losange
        max_area_ratio: float = 0.7, # % max de la frame
        symmetry_thresh: float = 0.25, # tolérance sur l'égalité des côtés
    ):
        self.min_area       = min_area
        self.max_area_ratio = max_area_ratio
        self.symmetry_thresh = symmetry_thresh
        self._clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))

    # ── API principale ────────────────────────────────────────────
    def detect(self, frame: np.ndarray) -> CardRegion | None:
        """
        Cherche le meilleur losange dans la frame.
        Retourne None si aucun trouvé.
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if len(frame.shape) == 3 else frame
        enhanced = self._clahe.apply(gray)

        # Edge detection avec double seuil adaptatif
        med = float(np.median(enhanced))
        lo  = max(0,   int(0.55 * med))
        hi  = min(255, int(1.45 * med))
        edges = cv2.Canny(enhanced, lo, hi)

        # Dilater légèrement pour fermer les contours partiels (doigts)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        edges  = cv2.dilate(edges, kernel, iterations=1)

        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        frame_area = frame.shape[0] * frame.shape[1]
        best: CardRegion | None = None

        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < self.min_area or area > frame_area * self.max_area_ratio:
                continue

            # Approximation polygonale
            peri   = cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, 0.04 * peri, True)

            if len(approx) != 4:
                continue
            if not cv2.isContourConvex(approx):
                continue

            corners = approx.reshape(4, 2).astype(np.float32)
            conf    = self._rhombus_score(corners)

            if conf < 0.5:
                continue

            warped = self._warp(frame, corners)
            region = CardRegion(corners=corners, warped=warped,
                                area=area, confidence=conf)

            if best is None or region.area > best.area:
                best = region

        return best

    # ── Validation du losange ─────────────────────────────────────
    def _rhombus_score(self, pts: np.ndarray) -> float:
        """
        Score 0→1 basé sur l'égalité des 4 côtés et la diagonale.
        Un losange parfait → score = 1.0.
        """
        ordered = self._order_diamond(pts)
        sides = []
        for i in range(4):
            a, b = ordered[i], ordered[(i + 1) % 4]
            sides.append(float(np.linalg.norm(b - a)))

        mean_s = np.mean(sides)
        if mean_s < 1:
            return 0.0
        cv_ = np.std(sides) / mean_s   # coefficient de variation
        score = max(0.0, 1.0 - cv_ / self.symmetry_thresh)
        return min(score, 1.0)

    # ── Perspective warp ──────────────────────────────────────────
    def _warp(self, frame: np.ndarray, pts: np.ndarray) -> np.ndarray:
        ordered = self._order_diamond(pts)
        # top, right, bottom, left → dst carré 400×400
        half = WARP_SIZE // 2
        dst  = np.array([
            [half,           0          ],  # top
            [WARP_SIZE - 1,  half       ],  # right
            [half,           WARP_SIZE-1],  # bottom
            [0,              half       ],  # left
        ], dtype=np.float32)

        M      = cv2.getPerspectiveTransform(ordered, dst)
        warped = cv2.warpPerspective(frame, M, (WARP_SIZE, WARP_SIZE))
        return warped

    @staticmethod
    def _order_diamond(pts: np.ndarray) -> np.ndarray:
        """Ordonne les 4 coins : top, right, bottom, left."""
        cx = pts[:, 0].mean()
        cy = pts[:, 1].mean()

        def angle(p):
            return float(np.arctan2(p[1] - cy, p[0] - cx))

        sorted_pts = sorted(pts.tolist(), key=lambda p: angle(p))
        # arctan2 : right(0°) → bottom(90°) → left(180°) → top(-90°)
        # on veut top, right, bottom, left
        # top = max neg y (min y), right = max x, bottom = max y, left = min x
        arr = np.array(sorted_pts, dtype=np.float32)
        top    = arr[np.argmin(arr[:, 1])]
        bottom = arr[np.argmax(arr[:, 1])]
        left   = arr[np.argmin(arr[:, 0])]
        right  = arr[np.argmax(arr[:, 0])]
        return np.array([top, right, bottom, left], dtype=np.float32)

    # ── Debug ─────────────────────────────────────────────────────
    @staticmethod
    def draw_debug(frame: np.ndarray, region: CardRegion) -> np.ndarray:
        out = frame.copy()
        corners = region.corners.astype(np.int32)
        cv2.polylines(out, [corners], True, (0, 255, 100), 2)
        for pt in corners:
            cv2.circle(out, tuple(pt), 5, (0, 255, 100), -1)
        cx = int(corners[:, 0].mean())
        cy = int(corners[:, 1].mean())
        cv2.putText(out, f"conf={region.confidence:.2f} area={int(region.area)}",
                    (cx - 60, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 100), 1)
        return out
