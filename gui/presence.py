# -*- coding: utf-8 -*-
"""
Presence detection:
- mode 'yolo_person': Ultralytics YOLO detects 'person'
- mode 'motion': simple frame-diff motion detector

Outputs: PresenceResult(present, score, detail)
"""

from __future__ import annotations
from dataclasses import dataclass

try:
    import cv2  # type: ignore
except Exception:
    cv2 = None

try:
    from ultralytics import YOLO  # type: ignore
except Exception:
    YOLO = None


@dataclass
class PresenceResult:
    present: bool
    score: float
    detail: str = ""


class PresenceDetector:
    def __init__(self):
        self.mode = "yolo_person"
        self.min_conf = 0.60

        # motion
        self.motion_thresh = 25
        self.motion_area_ratio = 0.01
        self._prev_gray = None

        # yolo
        self.model_path = "yolov8n.pt"
        self._model = None

    def available_yolo(self) -> bool:
        return YOLO is not None

    def load_yolo(self) -> bool:
        if YOLO is None:
            return False
        if self._model is None:
            self._model = YOLO(self.model_path)
        return True

    def detect(self, frame_bgr) -> PresenceResult:
        if self.mode == "motion":
            return self._detect_motion(frame_bgr)
        return self._detect_yolo_person(frame_bgr)

    def _detect_motion(self, frame_bgr) -> PresenceResult:
        if cv2 is None:
            return PresenceResult(False, 0.0, "opencv missing")
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (9, 9), 0)

        if self._prev_gray is None:
            self._prev_gray = gray
            return PresenceResult(False, 0.0, "warming up")

        diff = cv2.absdiff(self._prev_gray, gray)
        _, th = cv2.threshold(diff, self.motion_thresh, 255, cv2.THRESH_BINARY)
        changed = int((th > 0).sum())
        total = int(th.size)
        ratio = changed / max(1, total)
        self._prev_gray = gray
        present = ratio >= self.motion_area_ratio
        return PresenceResult(present, float(ratio), f"motion_ratio={ratio:.4f}")

    def _detect_yolo_person(self, frame_bgr) -> PresenceResult:
        if YOLO is None:
            return PresenceResult(False, 0.0, "ultralytics missing")
        self.load_yolo()
        try:
            results = self._model.predict(
                source=frame_bgr,
                conf=float(self.min_conf),
                iou=0.45,
                max_det=5,
                classes=[0],  # person
                verbose=False,
            )
        except Exception as e:
            return PresenceResult(False, 0.0, f"yolo error: {e}")

        if not results:
            return PresenceResult(False, 0.0, "no results")
        r0 = results[0]
        boxes = getattr(r0, "boxes", None)
        if boxes is None or len(boxes) == 0:
            return PresenceResult(False, 0.0, "no person")
        try:
            confs = boxes.conf.cpu().numpy()
        except Exception:
            confs = boxes.conf
        best = float(max(confs)) if len(confs) else 0.0
        return PresenceResult(best >= self.min_conf, best, "person")
