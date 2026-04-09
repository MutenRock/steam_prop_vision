"""
steamcore/recognition/card_detector.py
v2 -- Detection fond-independante via SIFT + homographie RANSAC.

Plus de detection de contour Canny.
On cherche directement la carte dans la frame entiere par matching de keypoints.
Retourne une CardRegion avec :
  - warped  : patch 400x400 normalise de la carte detectee
  - corners : 4 coins dans la frame originale
  - match_count : nb de keypoints valides
"""
from __future__ import annotations
import cv2
import numpy as np
from dataclasses import dataclass


@dataclass
class CardRegion:
    warped:      np.ndarray              # 400x400 BGR
    corners:     np.ndarray              # (4,2) float32 dans la frame
    match_count: int


class CardDetector:
    """
    Detection sans contrainte de fond.
    Chaque template SIFT est compare a la frame entiere.
    Si une homographie valide est trouvee, on extrait et redresse le patch.

    Usage :
        detector = CardDetector()
        region   = detector.detect(frame_rgb_or_bgr)
    """

    WARP_SIZE   = 400
    MIN_MATCHES = 8       # keypoints RANSAC minimum pour valider
    RATIO_TEST  = 0.75    # ratio Lowe
    MIN_INLIERS = 6       # inliers RANSAC minimum

    def __init__(
        self,
        platest_dir: str = "PLATEST",
        min_matches: int = MIN_MATCHES,
        min_inliers: int = MIN_INLIERS,
        ratio_test:  float = RATIO_TEST,
        # compat ancienne API (ignore)
        min_area: int = 0,
    ):
        self.platest_dir = platest_dir
        self.min_matches = min_matches
        self.min_inliers = min_inliers
        self.ratio_test  = ratio_test

        self._sift    = cv2.SIFT_create(nfeatures=1000)
        self._matcher = cv2.BFMatcher(cv2.NORM_L2)
        self._templates: list[_Template] = []
        self._load_templates()

    # ── API publique ──────────────────────────────────────────
    def detect(self, frame: np.ndarray) -> CardRegion | None:
        """
        Cherche n'importe quelle carte dans la frame.
        Retourne la premiere trouvee avec la meilleure homographie.
        """
        gray = self._to_gray(frame)
        kps_f, desc_f = self._sift.detectAndCompute(gray, None)
        if desc_f is None or len(kps_f) < self.min_matches:
            return None

        best: tuple[float, CardRegion] | None = None

        for tmpl in self._templates:
            region = self._match_template(tmpl, kps_f, desc_f, frame)
            if region is None:
                continue
            score = region.match_count
            if best is None or score > best[0]:
                best = (score, region)

        return best[1] if best else None

    def detect_for(self, frame: np.ndarray, card_id: str) -> CardRegion | None:
        """Cherche UNE carte specifique dans la frame."""
        gray = self._to_gray(frame)
        kps_f, desc_f = self._sift.detectAndCompute(gray, None)
        if desc_f is None:
            return None
        for tmpl in self._templates:
            if tmpl.card_id == card_id:
                return self._match_template(tmpl, kps_f, desc_f, frame)
        return None

    def reload(self):
        self._templates.clear()
        self._load_templates()

    # ── Interne ───────────────────────────────────────────────
    def _load_templates(self):
        p = Path(self.platest_dir)
        if not p.exists():
            print("[detector] PLATEST introuvable : " + str(p))
            return
        for subdir in sorted(p.iterdir()):
            if not subdir.is_dir():
                continue
            imgs = list(subdir.glob("*.jpg")) + list(subdir.glob("*.png"))
            if not imgs:
                continue
            tmpl = _Template(card_id=subdir.name, paths=imgs, sift=self._sift)
            if tmpl.descs:
                self._templates.append(tmpl)
                print("[detector] loaded " + subdir.name +
                      " (" + str(len(tmpl.descs)) + " imgs)")

    def _match_template(
        self,
        tmpl: "_Template",
        kps_f, desc_f,
        frame: np.ndarray,
    ) -> CardRegion | None:

        best_inliers = 0
        best_H       = None
        best_tmpl_sz = None

        for (kps_t, desc_t, tmpl_h, tmpl_w) in tmpl.descs:
            # Matching + ratio test
            matches = self._matcher.knnMatch(desc_t, desc_f, k=2)
            good = []
            for pair in matches:
                if len(pair) == 2:
                    m, n = pair
                    if m.distance < self.ratio_test * n.distance:
                        good.append(m)

            if len(good) < self.min_matches:
                continue

            pts_t = np.float32([kps_t[m.queryIdx].pt for m in good])
            pts_f = np.float32([kps_f[m.trainIdx].pt for m in good])

            H, mask = cv2.findHomography(pts_t, pts_f, cv2.RANSAC, 5.0)
            if H is None:
                continue

            inliers = int(mask.sum())
            if inliers >= self.min_inliers and inliers > best_inliers:
                best_inliers = inliers
                best_H       = H
                best_tmpl_sz = (tmpl_w, tmpl_h)

        if best_H is None:
            return None

        # Projeter les coins du template dans la frame
        w, h = best_tmpl_sz
        corners_t = np.float32([[0,0],[w,0],[w,h],[0,h]]).reshape(-1,1,2)
        corners_f = cv2.perspectiveTransform(corners_t, best_H).reshape(-1,2)

        # Valider que les coins forment un quadrilatere convexe raisonnable
        if not self._is_valid_quad(corners_f, frame.shape):
            return None

        # Warp perspective -> patch 400x400 normalise
        dst = np.float32([
            [0,                   0],
            [self.WARP_SIZE-1,    0],
            [self.WARP_SIZE-1,    self.WARP_SIZE-1],
            [0,                   self.WARP_SIZE-1],
        ])
        M      = cv2.getPerspectiveTransform(corners_f.astype(np.float32), dst)
        warped = cv2.warpPerspective(frame, M,
                                     (self.WARP_SIZE, self.WARP_SIZE))

        return CardRegion(warped=warped, corners=corners_f,
                          match_count=best_inliers)

    @staticmethod
    def _to_gray(frame: np.ndarray) -> np.ndarray:
        if len(frame.shape) == 2:
            return frame
        return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    @staticmethod
    def _is_valid_quad(corners: np.ndarray, shape) -> bool:
        h, w = shape[:2]
        # Tous les coins dans la frame
        for x, y in corners:
            if x < 0 or y < 0 or x > w or y > h:
                return False
        # Aire minimale (evite les quads degeneres)
        area = cv2.contourArea(corners.astype(np.float32))
        if area < 2000:
            return False
        # Convexite
        hull = cv2.convexHull(corners.astype(np.float32))
        if len(hull) != 4:
            return False
        return True


class _Template:
    """Un template = un dossier PLATEST avec N images."""
    def __init__(self, card_id: str, paths, sift):
        self.card_id = card_id
        self.descs: list[tuple] = []   # (kps, desc, h, w)
        for p in paths:
            img = cv2.imread(str(p))
            if img is None:
                continue
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            kps, desc = sift.detectAndCompute(gray, None)
            if desc is not None and len(kps) >= 8:
                self.descs.append((kps, desc, img.shape[0], img.shape[1]))
