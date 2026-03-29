# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import List
from .base import BaseDetector

def build_detectors(config: dict) -> List[BaseDetector]:
    """
    Construit la liste des détecteurs depuis config.json.

    Format attendu dans config.json :
    {
      "detectors": [
        {"type": "presence", "mode": "yolo_person", "model": "yolov8n.pt"},
        {"type": "yolo_classes", "classes": ["bottle", "book"], "confidence": 0.7}
      ]
    }
    """
    from .yolo_classes import YoloClassesDetector
    from .presence import PresenceDetector
    # from .plaque import PlaqueDetector  # décommenter quand prêt

    detectors: List[BaseDetector] = []
    for d_conf in config.get("detectors", []):
        dtype = str(d_conf.get("type", "")).strip().lower()
        if dtype == "yolo_classes":
            d: BaseDetector = YoloClassesDetector()
        elif dtype == "presence":
            d = PresenceDetector()
        # elif dtype == "plaque":
        #     d = PlaqueDetector()
        else:
            print(f"[factory] Unknown detector type: '{dtype}' — skipped")
            continue
        d.load_config(d_conf)
        detectors.append(d)
    return detectors
