"""
steamcore/recognition/card_detector.py
v2 -- Detection fond-independante via SIFT + homographie RANSAC.
"""
from __future__ import annotations
from pathlib import Path

import cv2
import numpy as np
from dataclasses import dataclass


def _find_images(directory: Path) -> list[Path]:
    exts = ["*.jpg", "*.jpeg", "*.png", "*.JPG", "*.JPEG", "*.PNG", "*.webp"]
    imgs = []
    for ext in exts:
        imgs.extend(directory.glob(ext))
    return imgs


@dataclass
class CardRegion:
    warped:      np.ndarray
    corners:     np.ndarray
    match_count: int


class CardDetector:
    WARP_SIZE   = 400
    MIN_MATCHES = 8
    RATIO_TEST  = 0.75
    MIN_INLIERS = 6

    def __init__(
        self,
        platest_dir: str  = "PLATEST",
        min_matches: int  = 8,
        min_inliers: int  = 6,
        ratio_test: float = 0.75,
        min_area: int     = 0,
    ):
        self.platest_dir = platest_dir
        self.min_matches = min_matches
        self.min_inliers = min_inliers
        self.ratio_test  = ratio_test
        self._sift    = cv2.SIFT_create(nfeatures=1000)
        self._matcher = cv2.BFMatcher(cv2.NORM_L2)
        self._templates: list[_Template] = []
        self._load_templates()

    def detect(self, frame: np.ndarray):
        gray = self._to_gray(frame)
        kps_f, desc_f = self._sift.detectAndCompute(gray, None)
        if desc_f is None or len(kps_f) < self.min_matches:
            return None
        best = None
        for tmpl in self._templates:
            region = self._match_template(tmpl, kps_f, desc_f, frame)
            if region is None:
                continue
            if best is None or region.match_count > best.match_count:
                best = region
        return best

    def detect_for(self, frame: np.ndarray, card_id: str):
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
            tmpl = _Template(subdir.name, imgs, self._sift)
            if tmpl.descs:
                self._templates.append(tmpl)
                print("[detector] loaded " + subdir.name +
                      " (" + str(len(tmpl.descs)) + " imgs)")
        print("[detector] " + str(len(self._templates)) + " templates charges")

    def _match_template(self, tmpl, kps_f, desc_f, frame):
        best_inliers = 0
        best_H       = None
        best_tmpl_sz = None
        for (kps_t, desc_t, tmpl_h, tmpl_w) in tmpl.descs:
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
        w, h = best_tmpl_sz
        corners_t = np.float32([[0,0],[w,0],[w,h],[0,h]]).reshape(-1,1,2)
        corners_f = cv2.perspectiveTransform(corners_t, best_H).reshape(-1,2)
        if not self._is_valid_quad(corners_f, frame.shape):
            return None
        M = cv2.getPerspectiveTransform(
            corners_f.astype(np.float32),
            np.float32([[0,0],[self.WARP_SIZE-1,0],
                        [self.WARP_SIZE-1,self.WARP_SIZE-1],[0,self.WARP_SIZE-1]])
        )
        warped = cv2.warpPerspective(frame, M, (self.WARP_SIZE, self.WARP_SIZE))
        return CardRegion(warped=warped, corners=corners_f, match_count=best_inliers)

    @staticmethod
    def _to_gray(frame: np.ndarray) -> np.ndarray:
        if len(frame.shape) == 2:
            return frame
        return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    @staticmethod
    def _is_valid_quad(corners: np.ndarray, shape) -> bool:
        h, w = shape[:2]
        for x, y in corners:
            if x < 0 or y < 0 or x > w or y > h:
                return False
        area = cv2.contourArea(corners.astype(np.float32))
        if area < 2000:
            return False
        hull = cv2.convexHull(corners.astype(np.float32))
        if len(hull) != 4:
            return False
        return True


class _Template:
    def __init__(self, card_id: str, paths, sift):
        self.card_id = card_id
        self.descs: list[tuple] = []
        for p in paths:
            img = cv2.imread(str(p))
            if img is None:
                continue
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            kps, desc = sift.detectAndCompute(gray, None)
            if desc is not None and len(kps) >= 8:
                self.descs.append((kps, desc, img.shape[0], img.shape[1]))
