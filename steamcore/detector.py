from __future__ import annotations
from dataclasses import dataclass
from ultralytics import YOLO
import numpy as np

@dataclass
class Detection:
    label:      str
    confidence: float

class YOLODetector:
    def __init__(self, model_path="yolov8n.pt", imgsz=320, conf=0.5,
                 confirm_frames=1):  # confirm_frames gardé pour compat mais ignoré
        self.model  = YOLO(model_path)
        self.imgsz  = imgsz
        self.conf   = conf

    def process(self, frame: np.ndarray) -> Detection | None:
        """Retourne la première détection avec le score le plus élevé, ou None."""
        results = self.model.predict(frame, imgsz=self.imgsz,
                                     conf=self.conf, verbose=False)
        best = None
        for r in results:
            for box in r.boxes:
                label = self.model.names[int(box.cls)]
                conf  = float(box.conf)
                if best is None or conf > best.confidence:
                    best = Detection(label=label, confidence=conf)
        return best

    def detect_person(self, frame: np.ndarray) -> bool:
        d = self.process(frame)
        return d is not None and d.label == "person"
