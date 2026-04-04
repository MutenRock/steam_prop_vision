from __future__ import annotations
import cv2
import numpy as np
from dataclasses import dataclass

WARP_SIZE = 400

@dataclass
class CardRegion:
    corners: np.ndarray
    warped:  np.ndarray

class CardDetector:
    def __init__(self, min_area=1500):
        self.min_area = min_area
        self._clahe   = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))

    def detect(self, frame: np.ndarray) -> CardRegion | None:
        gray     = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        enhanced = self._clahe.apply(gray)
        med      = float(np.median(enhanced))
        edges    = cv2.Canny(enhanced, max(0, int(0.55*med)), min(255, int(1.45*med)))
        kernel   = cv2.getStructuringElement(cv2.MORPH_RECT, (3,3))
        edges    = cv2.dilate(edges, kernel, iterations=1)

        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        best = None

        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < self.min_area or area > frame.shape[0]*frame.shape[1]*0.7:
                continue
            peri   = cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, 0.04*peri, True)
            if len(approx) != 4 or not cv2.isContourConvex(approx):
                continue
            pts   = approx.reshape(4, 2).astype(np.float32)
            sides = [float(np.linalg.norm(pts[(i+1)%4]-pts[i])) for i in range(4)]
            mean  = sum(sides)/4
            if mean < 1 or (max(sides)-min(sides))/mean > 0.35:
                continue
            if best is None or area > best[0]:
                best = (area, pts)

        if best is None:
            return None

        corners = best[1]
        warped  = self._warp(frame, corners)
        return CardRegion(corners=corners, warped=warped)

    def _warp(self, frame, pts):
        ordered = self._order(pts)
        half    = WARP_SIZE // 2
        dst     = np.array([[half,0],[WARP_SIZE-1,half],[half,WARP_SIZE-1],[0,half]], dtype=np.float32)
        M       = cv2.getPerspectiveTransform(ordered, dst)
        return cv2.warpPerspective(frame, M, (WARP_SIZE, WARP_SIZE))

    @staticmethod
    def _order(pts):
        return np.array([
            pts[np.argmin(pts[:,1])],   # top
            pts[np.argmax(pts[:,0])],   # right
            pts[np.argmax(pts[:,1])],   # bottom
            pts[np.argmin(pts[:,0])],   # left
        ], dtype=np.float32)
