# -*- coding: utf-8 -*-
"""
Action Router (v5)
------------------
Loads rules.json from the selected config folder and executes actions when
validated events happen (presence/plaque).

Event keys:
- "presence"
- "PLAQUE:<plaque_id>"

Rules JSON format (rules.json):
{
  "version": 1,
  "rules": [
    {
      "when": "presence",
      "cooldown_s": 2.0,
      "then": [
        {"type": "udp", "msg": "CMD:START"}
      ]
    },
    {
      "when": "PLAQUE:plaque_A",
      "require_presence": true,
      "cooldown_s": 2.0,
      "then": [
        {"type": "udp", "msg": "LOXONE:LIGHTS=ON"},
        {"type": "udp", "msg": "CMD:START"}
      ]
    }
  ]
}

Supported actions:
- {"type":"udp","msg":"..."}  -> injected into SimulationEngine as UDP RX
- {"type":"inject_detection","label":"...","conf":0.9}  -> inject detection directly
- {"type":"log","msg":"..."}  -> GUI log line (returned as side effect message)
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import json, os, time


@dataclass
class Rule:
    when: str
    then: List[Dict[str, Any]]
    cooldown_s: float = 0.0
    require_presence: bool = False


class ActionRouter:
    def __init__(self):
        self.rules: List[Rule] = []
        self._last_fire: Dict[str, float] = {}
        self.loaded_from: Optional[str] = None

    def load_rules(self, config_folder: str) -> Tuple[bool, str]:
        """
        Tries to load rules.json from config folder.
        If missing, keeps empty rules.
        """
        path = os.path.join(config_folder, "rules.json")
        if not os.path.isfile(path):
            self.rules = []
            self.loaded_from = None
            return False, "rules.json not found (no actions)"
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            rules_raw = data.get("rules", [])
            rules: List[Rule] = []
            for r in rules_raw:
                when = str(r.get("when", "")).strip()
                then = r.get("then", [])
                if not when or not isinstance(then, list):
                    continue
                cooldown_s = float(r.get("cooldown_s", 0.0))
                require_presence = bool(r.get("require_presence", False))
                rules.append(Rule(when=when, then=then, cooldown_s=cooldown_s, require_presence=require_presence))
            self.rules = rules
            self.loaded_from = path
            self._last_fire.clear()
            return True, f"Loaded {len(rules)} rule(s)"
        except Exception as e:
            self.rules = []
            self.loaded_from = None
            return False, f"Failed to load rules.json: {e}"

    def handle(self, *,
               key: str,
               presence: bool,
               sim_engine,
               default_conf: float = 0.9) -> List[str]:
        """
        Executes actions for matching rules, respecting require_presence and cooldown.
        Returns list of log strings describing executed actions.
        """
        logs: List[str] = []
        now = time.time()
        for rule in self.rules:
            if rule.when != key:
                continue
            if rule.require_presence and not presence:
                continue
            # cooldown per rule key
            last = self._last_fire.get(rule.when, 0.0)
            if rule.cooldown_s > 0 and (now - last) < rule.cooldown_s:
                continue
            self._last_fire[rule.when] = now

            for act in rule.then:
                if not isinstance(act, dict):
                    continue
                typ = str(act.get("type", "")).strip().lower()
                if typ == "udp":
                    msg = str(act.get("msg", "")).strip()
                    if msg:
                        sim_engine.inject_udp(msg)
                        logs.append(f"[action] udp: {msg}")
                elif typ == "inject_detection":
                    label = str(act.get("label", "")).strip()
                    conf = float(act.get("conf", default_conf))
                    if label:
                        sim_engine.inject_detection(label, conf)
                        logs.append(f"[action] inject_detection: {label} ({conf:.2f})")
                elif typ == "log":
                    msg = str(act.get("msg", "")).strip()
                    if msg:
                        logs.append(f"[action] {msg}")
        return logs
