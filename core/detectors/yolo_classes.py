# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Dict, List
from .base import BaseDetector, DetectionResult

class YoloClassesDetector(BaseDetector):
    """
    Détecte n'importe quelle classe YOLO.
    classes: [] = toutes les classes acceptées.
    Stabilisation sur stable_frames consécutives.
    """

    def __init__(self):
        self._model = None
        self._target_classes: List[str] = []
        self._confidence: float = 0.6
        self._stable_frames: int = 15
        self._counters: Dict[str, int] = {}

    def load_config(self, config: dict) -> None:
        from ultralytics import YOLO
        model_path = config.get("model", "yolov8n.pt")
        self._model = YOLO(model_path)
        self._target_classes = [c.lower() for c in config.get("classes", [])]
        self._confidence = float(config.get("confidence", 0.6))
        self._stable_frames = int(config.get("stable_frames", 15))
        self._counters = {}

    def process_frame(self, frame) -> List[DetectionResult]:
        if self._model is None:
            return []

        results = self._model(frame, verbose=False)[0]
        seen: set = set()
        detections: List[DetectionResult] = []

        for box in results.boxes:
            conf = float(box.conf)
            cls_name = self._model.names[int(box.cls)].lower()
            if conf < self._confidence:
                continue
            if self._target_classes and cls_name not in self._target_classes:
                continue
            seen.add(cls_name)
            self._counters[cls_name] = self._counters.get(cls_name, 0) + 1
            if self._counters[cls_name] >= self._stable_frames:
                detections.append(DetectionResult(
                    label=cls_name,
                    confidence=conf,
                    meta={"bbox": box.xyxy.tolist()}
                ))

        for k in list(self._counters):
            if k not in seen:
                self._counters[k] = 0

        return detections

    def reset(self) -> None:
        self._counters = {}
