from __future__ import annotations
from ultralytics import YOLO
import numpy as np

class Detection:
    def __init__(self, label: str, confidence: float):
        self.label      = label
        self.confidence = confidence

class YOLODetector:
    def __init__(self, model_path="yolov8n.pt", imgsz=320, conf=0.5, target_label="person"):
        self.model        = YOLO(model_path)
        self.imgsz        = imgsz
        self.conf         = conf
        self.target_label = target_label

    def detect_person(self, frame: np.ndarray) -> bool:
        """Retourne True si une personne est visible dans la frame."""
        results = self.model.predict(frame, imgsz=self.imgsz,
                                     conf=self.conf, verbose=False)
        for r in results:
            for box in r.boxes:
                label = self.model.names[int(box.cls)]
                if label == self.target_label:
                    return True
        return False
