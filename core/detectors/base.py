# -*- coding: utf-8 -*-
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List

@dataclass
class DetectionResult:
    label: str
    confidence: float
    meta: Dict[str, Any] = field(default_factory=dict)

class BaseDetector(ABC):
    @abstractmethod
    def process_frame(self, frame) -> List[DetectionResult]:
        ...

    @abstractmethod
    def load_config(self, config: dict) -> None:
        ...

    def reset(self) -> None:
        pass
