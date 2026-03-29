# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import List
from .base import BaseDetector, DetectionResult

class PresenceDetector(BaseDetector):
    """
    Détecte la présence humaine via YOLO (yolo_person) ou mouvement (motion).
    Émet le label 'presence'.
    """

    def __init__(self):
        self._model = None
        self._mode: str = "yolo_person"
        self._confidence: float = 0.5
        self._stable_frames: int = 10
        self._counter: int = 0
        self._prev_gray = None

    def load_config(self, config: dict) -> None:
        self._mode = config.get("mode", "yolo_person")
        self._confidence = float(config.get("confidence", 0.5))
        self._stable_frames = int(config.get("stable_frames", 10))
        self._counter = 0
        self._prev_gray = None
        if self._mode == "yolo_person":
            from ultralytics import YOLO
            model_path = config.get("model", "yolov8n.pt")
            self._model = YOLO(model_path)

    def process_frame(self, frame) -> List[DetectionResult]:
        if self._mode == "yolo_person":
            return self._detect_yolo(frame)
        return self._detect_motion(frame)

    def _detect_yolo(self, frame) -> List[DetectionResult]:
        if self._model is None:
            return []
        results = self._model(frame, verbose=False)[0]
        persons = [
            b for b in results.boxes
            if self._model.names[int(b.cls)] == "person"
            and float(b.conf) >= self._confidence
        ]
        if persons:
            self._counter += 1
        else:
            self._counter = 0
        if self._counter >= self._stable_frames:
            score = max(float(b.conf) for b in persons)
            return [DetectionResult(label="presence", confidence=score)]
        return []

    def _detect_motion(self, frame) -> List[DetectionResult]:
        import cv2
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)
        if self._prev_gray is None:
            self._prev_gray = gray
            return []
        diff = cv2.absdiff(self._prev_gray, gray)
        self._prev_gray = gray
        _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
        motion_ratio = thresh.sum() / (thresh.size * 255)
        if motion_ratio > 0.02:
            self._counter += 1
        else:
            self._counter = 0
        if self._counter >= self._stable_frames:
            return [DetectionResult(label="presence", confidence=round(min(1.0, motion_ratio * 10), 2))]
        return []

    def reset(self) -> None:
        self._counter = 0
        self._prev_gray = None
