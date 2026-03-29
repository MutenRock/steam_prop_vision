# -*- coding: utf-8 -*-
"""
Core simulation: Player/UDP/FSM + inject detection/udp.

The 'detection' label is generic (e.g., 'presence', 'PLAQUE:plaque_A').
A RuleEngine (GUI side) decides what to inject and when.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple, Any
import random


@dataclass
class Event:
    t: float
    type: str
    payload: Dict[str, Any] = field(default_factory=dict)

class EventBus:
    def __init__(self):
        self._subs: Dict[str, List[Callable[[Event], None]]] = {}

    def subscribe(self, event_type: str, cb: Callable[[Event], None]) -> None:
        self._subs.setdefault(event_type, []).append(cb)

    def emit(self, ev: Event) -> None:
        for cb in self._subs.get(ev.type, []):
            cb(ev)


class RingLogger:
    def __init__(self, max_lines: int = 800):
        self.max_lines = max_lines
        self.lines: List[str] = []

    def log(self, t: float, src: str, msg: str) -> None:
        s = f"[t={t:05.1f}] [{src:<12}] {msg}"
        self.lines.append(s)
        if len(self.lines) > self.max_lines:
            self.lines = self.lines[-self.max_lines:]

    def tail(self, n: int = 250) -> str:
        return "\n".join(self.lines[-n:])


class SimVideoPlayer:
    def __init__(self, bus: EventBus, logger: RingLogger):
        self.bus = bus
        self.logger = logger
        self.current: Optional[Tuple[str, float, float]] = None

    def play(self, t: float, name: str, duration_s: float) -> None:
        self.current = (name, t, t + duration_s)
        self.logger.log(t, "player", f"PLAY '{name}' duration={duration_s:.1f}s")

    def stop(self, t: float) -> None:
        if self.current:
            name, _, _ = self.current
            self.logger.log(t, "player", f"STOP '{name}'")
        self.current = None

    def tick(self, t: float) -> None:
        if not self.current:
            return
        name, _, end_t = self.current
        if t >= end_t:
            self.logger.log(t, "player", f"FINISHED '{name}'")
            self.current = None
            self.bus.emit(Event(t, "video.finished", {"name": name}))

    def status(self) -> Dict[str, Any]:
        if not self.current:
            return {"playing": False, "name": None}
        name, start, end = self.current
        return {"playing": True, "name": name, "start": start, "end": end}


class SimUdpLink:
    def __init__(self, bus: EventBus, logger: RingLogger):
        self.bus = bus
        self.logger = logger
        bus.subscribe("world.udp_injected", self._on_injected)
        bus.subscribe("state.changed", self._on_state_changed)

    def _on_injected(self, ev: Event) -> None:
        msg = str(ev.payload.get("msg", ""))
        self.logger.log(ev.t, "udp", f"RX '{msg}'")
        self.bus.emit(Event(ev.t, "udp.rx", {"msg": msg}))

    def _on_state_changed(self, ev: Event) -> None:
        state = str(ev.payload.get("state", "?"))
        self.logger.log(ev.t, "udp", f"TX STATE='{state}'")


class Mission1StateMachine:
    """
    Generic mission FSM:
      IDLE -> DETECTED -> PLAY_INTRO -> PLAY_FULL -> DONE

    Trigger:
      - When engine receives yolo.detected with label in trigger_labels.
        (By default: any label triggers, but GUI config can restrict)
    """
    def __init__(self, bus: EventBus, logger: RingLogger, player: SimVideoPlayer):
        self.bus = bus
        self.logger = logger
        self.player = player
        self.state = "IDLE"
        self.locked_detection = False
        self.last_detection: Optional[Tuple[str, float]] = None
        self.trigger_labels: Optional[List[str]] = None  # None means accept any

        bus.subscribe("yolo.detected", self._on_detected)
        bus.subscribe("video.finished", self._on_video_finished)
        bus.subscribe("udp.rx", self._on_udp)

        self._set_state(0.0, "IDLE")

    def set_trigger_labels(self, labels: Optional[List[str]]) -> None:
        self.trigger_labels = labels

    def _set_state(self, t: float, new_state: str) -> None:
        if new_state == self.state:
            return
        self.state = new_state
        self.bus.emit(Event(t, "state.changed", {"state": self.state}))
        self.logger.log(t, "fsm", f"STATE -> {self.state}")

    def _start_sequence(self, t: float) -> None:
        if self.state != "IDLE":
            return
        self.locked_detection = True
        self._set_state(t, "DETECTED")
        self.player.play(t, "video_intro_tournee.mp4", duration_s=6.0)
        self._set_state(t, "PLAY_INTRO")

    def _label_allowed(self, label: str) -> bool:
        if self.trigger_labels is None:
            return True
        return label in self.trigger_labels

    def _on_detected(self, ev: Event) -> None:
        label = str(ev.payload.get("label", "unknown"))
        conf = float(ev.payload.get("conf", 0.0))
        self.last_detection = (label, conf)

        if not self._label_allowed(label):
            self.logger.log(ev.t, "fsm", f"ignored label '{label}' (not in trigger list)")
            return

        if self.locked_detection:
            self.logger.log(ev.t, "fsm", "detection ignored (locked)")
            return

        self._start_sequence(ev.t)

    def _on_video_finished(self, ev: Event) -> None:
        name = str(ev.payload.get("name", ""))
        if self.state == "PLAY_INTRO" and name == "video_intro_tournee.mp4":
            self.player.play(ev.t, "video_complete.mp4", duration_s=12.0)
            self._set_state(ev.t, "PLAY_FULL")
            return
        if self.state == "PLAY_FULL" and name == "video_complete.mp4":
            self._set_state(ev.t, "DONE")
            return

    def _on_udp(self, ev: Event) -> None:
        msg = str(ev.payload.get("msg", "")).strip().upper()
        if msg == "CMD:START":
            self.logger.log(ev.t, "fsm", "CMD:START")
            self._start_sequence(ev.t)
        elif msg == "CMD:RESET":
            self.logger.log(ev.t, "fsm", "CMD:RESET")
            self.player.stop(ev.t)
            self.locked_detection = False
            self.last_detection = None
            self._set_state(ev.t, "IDLE")
        elif msg == "CMD:STOP":
            self.logger.log(ev.t, "fsm", "CMD:STOP")
            self.player.stop(ev.t)
            self.locked_detection = False
            self._set_state(ev.t, "IDLE")

    def snapshot(self) -> Dict[str, Any]:
        ld = None
        if self.last_detection:
            ld = {"label": self.last_detection[0], "conf": self.last_detection[1]}
        return {
            "state": self.state,
            "locked_detection": self.locked_detection,
            "last_detection": ld,
            "trigger_labels": self.trigger_labels,
        }


class SimulationEngine:
    def __init__(self, seed: int = 42):
        random.seed(seed)
        self.bus = EventBus()
        self.logger = RingLogger()
        self.t = 0.0

        self.player = SimVideoPlayer(self.bus, self.logger)
        self.udp = SimUdpLink(self.bus, self.logger)
        self.fsm = Mission1StateMachine(self.bus, self.logger, self.player)

    def set_trigger_labels(self, labels: Optional[List[str]]) -> None:
        self.fsm.set_trigger_labels(labels)

    def inject_detection(self, label: str, conf: float) -> None:
        self.bus.emit(Event(self.t, "yolo.detected", {"label": label, "conf": float(conf)}))

    def inject_udp(self, msg: str) -> None:
        self.bus.emit(Event(self.t, "world.udp_injected", {"msg": msg}))

    def step(self, dt: float) -> None:
        self.player.tick(self.t)
        self.t = round(self.t + dt, 10)

    def snapshot(self) -> Dict[str, Any]:
        ps = self.player.status()
        remaining = 0.0
        if ps.get("playing"):
            remaining = max(0.0, float(ps["end"]) - self.t)
        return {
            "t": self.t,
            "fsm": self.fsm.snapshot(),
            "player": {
                "playing": ps.get("playing", False),
                "name": ps.get("name"),
                "remaining_s": remaining,
            },
            "log_tail": self.logger.tail(250),
        }
