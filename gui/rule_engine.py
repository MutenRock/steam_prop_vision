# -*- coding: utf-8 -*-
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
import time

from gui.presence import PresenceDetector, PresenceResult
from gui.plaque_recognizer import PlaqueRecognizer, PlaqueMatch

@dataclass
class Validated:
    presence: bool = False
    presence_score: float = 0.0
    plaque_id: Optional[str] = None
    plaque_score: float = 0.0
    detail: str = ""

class RuleEngine:
    def __init__(self):
        self.presence = PresenceDetector()
        self.plaque = PlaqueRecognizer()

        self.presence_stable_frames = 3
        self.plaque_stable_frames = 2
        self.presence_cooldown_s = 2.0
        self.plaque_cooldown_s = 2.0

        self.require_presence_for_plaque = True
        self.allowed_plaque_ids: Optional[List[str]] = None

        self._presence_hits = 0
        self._plaque_hits: Dict[str, int] = {}
        self._last_presence_emit = 0.0
        self._last_plaque_emit = 0.0
        self._presence_state = False

        self.last_presence: PresenceResult = PresenceResult(False, 0.0, "")
        self.last_plaque: Optional[PlaqueMatch] = None

    def apply_config(self, cfg: Dict[str, Any]) -> None:
        pres = cfg.get("presence", {})
        self.presence.mode = pres.get("mode", self.presence.mode)
        self.presence.min_conf = float(pres.get("min_conf", self.presence.min_conf))
        self.presence_stable_frames = int(pres.get("stable_frames", self.presence_stable_frames))
        self.presence_cooldown_s = float(pres.get("cooldown_s", self.presence_cooldown_s))

        pl = cfg.get("plaque", {})
        self.plaque.min_good_matches = int(pl.get("min_good_matches", self.plaque.min_good_matches))
        self.plaque_stable_frames = int(pl.get("stable_frames", self.plaque_stable_frames))
        self.plaque_cooldown_s = float(pl.get("cooldown_s", self.plaque_cooldown_s))
        self.require_presence_for_plaque = bool(pl.get("require_presence", self.require_presence_for_plaque))

        trig = cfg.get("trigger", {})
        allowed = trig.get("allowed_plaque_ids")
        self.allowed_plaque_ids = list(allowed) if isinstance(allowed, list) and allowed else None

    def process_frame(self, frame_bgr) -> Validated:
        out = Validated()
        now = time.time()

        pres = self.presence.detect(frame_bgr)
        self.last_presence = pres

        if pres.present:
            self._presence_hits += 1
        else:
            self._presence_hits = 0

        self._presence_state = self._presence_hits >= self.presence_stable_frames
        out.presence = self._presence_state
        out.presence_score = float(pres.score)

        plaque_match = self.plaque.recognize(frame_bgr) if self.plaque.is_available() else None
        self.last_plaque = plaque_match

        if plaque_match is not None:
            pid = plaque_match.plaque_id
            if self.allowed_plaque_ids is not None and pid not in self.allowed_plaque_ids:
                pid = None
            if pid is not None:
                self._plaque_hits[pid] = self._plaque_hits.get(pid, 0) + 1
        else:
            for k in list(self._plaque_hits.keys()):
                self._plaque_hits[k] = max(0, self._plaque_hits[k] - 1)
                if self._plaque_hits[k] == 0:
                    del self._plaque_hits[k]

        best_pid, best_hits = None, 0
        for pid, hits in self._plaque_hits.items():
            if hits > best_hits:
                best_pid, best_hits = pid, hits

        can_emit = (now - self._last_plaque_emit) >= self.plaque_cooldown_s
        if best_pid and best_hits >= self.plaque_stable_frames and can_emit:
            if (not self.require_presence_for_plaque) or self._presence_state:
                self._last_plaque_emit = now
                out.plaque_id = best_pid
                out.plaque_score = float(plaque_match.score if plaque_match else 0.0)
                out.detail = f"validated plaque {best_pid} hits={best_hits}"

        return out
