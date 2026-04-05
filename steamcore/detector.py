"""
steamcore/detector.py
YOLODetector -- retourne PersonFrame avec count + centroid + bbox
"""
from __future__ import annotations
import numpy as np
from dataclasses import dataclass
from ultralytics import YOLO
from steamcore.person_tracker import PersonFrame


class YOLODetector:
    def __init__(self, model_path="yolov8n.pt", imgsz=320, conf=0.5):
        self.model = YOLO(model_path)
        self.imgsz = imgsz
        self.conf  = conf

    def detect_persons(self, frame: np.ndarray) -> PersonFrame:
        results = self.model.predict(frame, imgsz=self.imgsz,
                                     conf=self.conf, verbose=False)
        persons = []
        for r in results:
            for box in r.boxes:
                if self.model.names[int(box.cls)] == "person":
                    x1, y1, x2, y2 = [int(v) for v in box.xyxy[0]]
                    persons.append((x1, y1, x2, y2, float(box.conf)))

        if not persons:
            return PersonFrame(count=0, centroid=None, bbox=None)

        # Prendre la detection avec le meilleur score comme "joueur principal"
        best = max(persons, key=lambda p: p[4])
        x1, y1, x2, y2, _ = best
        centroid = ((x1 + x2) / 2.0, (y1 + y2) / 2.0)
        return PersonFrame(count=len(persons), centroid=centroid, bbox=(x1,y1,x2,y2))

    # Compat ancienne API
    def detect_person(self, frame: np.ndarray) -> bool:
        return self.detect_persons(frame).count > 0
