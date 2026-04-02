"""
steamcore/detector.py
YOLO yolov8n.pt imgsz=320 — config validée BigEye :
  avg=54ms inférence → ~15 FPS pipeline réel sur STYX headless.
Confirmation : 3 détections consécutives avant trigger.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from collections import deque
import numpy as np


@dataclass
class Detection:
    label: str
    confidence: float


class YOLODetector:
    def __init__(
        self,
        model_path: str = "yolov8n.pt",
        imgsz: int = 320,
        conf: float = 0.5,
        confirm_frames: int = 3,   # frames consécutives pour confirmer
        target_labels: list[str] | None = None,
    ):
        self.imgsz = imgsz
        self.conf = conf
        self.confirm_frames = confirm_frames
        self.target_labels = set(target_labels) if target_labels else None

        from ultralytics import YOLO
        self._model = YOLO(model_path)

        # Historique par label pour confirmation
        self._history: dict[str, deque] = {}

    def process(self, frame: np.ndarray) -> Detection | None:
        """
        Retourne une Detection confirmée (3 frames consécutives)
        ou None si pas de détection stable.
        """
        results = self._model(frame, imgsz=self.imgsz, conf=self.conf, verbose=False)
        boxes = results[0].boxes

        detected_labels: set[str] = set()
        best: dict[str, float] = {}

        if boxes is not None:
            for box in boxes:
                label = self._model.names[int(box.cls[0])]
                conf_val = float(box.conf[0])
                if self.target_labels and label not in self.target_labels:
                    continue
                detected_labels.add(label)
                best[label] = max(best.get(label, 0.0), conf_val)

        # Mise à jour historique
        for label in list(self._history.keys()):
            if label not in detected_labels:
                self._history[label].clear()

        confirmed = None
        for label in detected_labels:
            if label not in self._history:
                self._history[label] = deque(maxlen=self.confirm_frames)
            self._history[label].append(best[label])
            if len(self._history[label]) == self.confirm_frames:
                avg_conf = sum(self._history[label]) / self.confirm_frames
                confirmed = Detection(label=label, confidence=round(avg_conf, 3))
                self._history[label].clear()  # reset après trigger
                break

        return confirmed
