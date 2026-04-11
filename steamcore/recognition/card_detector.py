"""
steamcore/recognition/card_detector.py
Niveau 2 -- identification precise sur ROI.
Supporte deux backends : ORB (rapide) et SIFT (precis).
Travaille sur la ROI retournee par FastDetector.
"""
from __future__ import annotations
from pathlib import Path
from dataclasses import dataclass
import cv2
import numpy as np


def _find_images(directory: Path) -> list:
    exts = ["*.jpg", "*.jpeg", "*.png", "*.JPG", "*.JPEG", "*.PNG", "*.webp"]
    imgs = []
    for ext in exts:
        imgs.extend(directory.rglob(ext))   # récursif : trouve images/ sous-dossier
    return [p for p in imgs if not p.name.startswith(".")]


@dataclass
class CardRegion:
    warped:      np.ndarray
    corners:     np.ndarray
    match_count: int
    card_id:     str | None = None


class CardDetector:
    """
    backend : "orb"  -> ORB  ~15-25fps sur Pi 5 sur ROI
    backend : "sift" -> SIFT ~10-15fps sur Pi 5 sur ROI
    """
    WARP_SIZE = 400

    def __init__(
        self,
        platest_dir:  str   = "PLATEST",
        backend:      str   = "orb",
        min_matches:  int   = 8,
        min_inliers:  int   = 6,
        ratio_test:   float = 0.75,
    ):
        self.platest_dir = platest_dir
        self.backend     = backend.lower()
        self.min_matches = min_matches
        self.min_inliers = min_inliers
        self.ratio_test  = ratio_test
        self._templates: list = []
        self._build_matcher()
        self._load_templates()

    def load_config(self, cfg: dict):
        cd = cfg.get("card_detector", {})
        self.backend     = cd.get("backend",      self.backend)
        self.min_matches = cd.get("min_matches",  self.min_matches)
        self.min_inliers = cd.get("min_inliers",  self.min_inliers)
        self.ratio_test  = cd.get("ratio_test",   self.ratio_test)
        self._build_matcher()
        self.reload()

    def _build_matcher(self):
        if self.backend == "sift":
            self._feat    = cv2.SIFT_create(nfeatures=800)
            self._matcher = cv2.BFMatcher(cv2.NORM_L2)
        else:
            self._feat    = cv2.ORB_create(nfeatures=600)
            self._matcher = cv2.BFMatcher(cv2.NORM_HAMMING)

    # ── public ───────────────────────────────────────────────────────────────

    def detect(self, roi: np.ndarray) -> CardRegion | None:
        gray = self._to_gray(roi)
        kps_f, desc_f = self._feat.detectAndCompute(gray, None)
        if desc_f is None or len(kps_f) < self.min_matches:
            return None
        best = None
        for tmpl in self._templates:
            region = self._match(tmpl, kps_f, desc_f, roi)
            if region is None:
                continue
            if best is None or region.match_count > best.match_count:
                best = region
        return best

    def reload(self):
        self._templates.clear()
        self._load_templates()

    @property
    def card_ids(self) -> list:
        return [t.card_id for t in self._templates]

    # ── private ──────────────────────────────────────────────────────────────

    def _load_templates(self):
        p = Path(self.platest_dir)
        if not p.exists():
            print("[detector] PLATEST introuvable : " + str(p))
            return
        for subdir in sorted(p.iterdir()):
            if not subdir.is_dir():
                continue
            imgs = _find_images(subdir)
            if not imgs:
                continue
            tmpl = _Template(subdir.name, imgs, self._feat)
            if tmpl.descs:
                self._templates.append(tmpl)
                print("[detector] loaded " + subdir.name +
                      " (" + str(len(tmpl.descs)) + " imgs)")
        print("[detector] " + str(len(self._templates)) +
              " templates charges (backend=" + self.backend + ")")

    def _match(self, tmpl, kps_f, desc_f, roi):
        best_inliers = 0
        best_H       = None
        best_sz      = None
        for (kps_t, desc_t, th, tw) in tmpl.descs:
            pairs = self._matcher.knnMatch(desc_t, desc_f, k=2)
            good  = []
            for pair in pairs:
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
                best_sz      = (tw, th)
        if best_H is None:
            return None
        w, h = best_sz
        c_t  = np.float32([[0,0],[w,0],[w,h],[0,h]]).reshape(-1,1,2)
        c_f  = cv2.perspectiveTransform(c_t, best_H).reshape(-1,2)
        if not _valid_quad(c_f, roi.shape):
            return None
        M = cv2.getPerspectiveTransform(
            c_f.astype(np.float32),
            np.float32([[0,0],[self.WARP_SIZE-1,0],
                        [self.WARP_SIZE-1,self.WARP_SIZE-1],[0,self.WARP_SIZE-1]])
        )
        warped = cv2.warpPerspective(roi, M, (self.WARP_SIZE, self.WARP_SIZE))
        return CardRegion(warped=warped, corners=c_f,
                          match_count=best_inliers, card_id=tmpl.card_id)

    @staticmethod
    def _to_gray(frame: np.ndarray) -> np.ndarray:
        return frame if len(frame.shape) == 2                else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


def _valid_quad(corners: np.ndarray, shape) -> bool:
    h, w = shape[:2]
    for x, y in corners:
        if x < 0 or y < 0 or x > w or y > h:
            return False
    return cv2.contourArea(corners.astype(np.float32)) > 500


class _Template:
    def __init__(self, card_id: str, paths, feat):
        self.card_id = card_id
        self.descs: list = []
        for p in paths:
            img = cv2.imread(str(p))
            if img is None:
                continue
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            kps, desc = feat.detectAndCompute(gray, None)
            if desc is not None and len(kps) >= 6:
                self.descs.append((kps, desc, img.shape[0], img.shape[1]))
