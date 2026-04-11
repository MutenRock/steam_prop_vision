"""
steamcore/rules.py
Moteur de règles S.T.E.A.M.

Charge config/rules.yaml et décide si un label détecté doit déclencher
des actions, en tenant compte de :
  - enabled          : label actif ?
  - cooldown         : délai minimum entre deux déclenchements
  - min_duration     : durée de détection continue requise (ex: 2s pour person)
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
    _YAML = True
except ImportError:
    import json
    _YAML = False
    print("[rules] WARN: pyyaml manquant, fallback JSON -> pip install pyyaml")


@dataclass
class ActionDef:
    type: str                     # audio | video | udp | http
    subdir: str = ""
    message: str = ""
    url: str = ""

    @staticmethod
    def from_dict(d: dict) -> "ActionDef":
        return ActionDef(
            type    = d.get("type", ""),
            subdir  = d.get("subdir", ""),
            message = d.get("message", ""),
            url     = d.get("url", ""),
        )


@dataclass
class LabelRule:
    label: str
    enabled: bool = True
    cooldown: float = 5.0
    min_duration: float = 0.0
    actions: list[ActionDef] = field(default_factory=list)


class RuleEngine:
    def __init__(self, config_path: str = "config/rules.yaml"):
        self.config_path = Path(config_path)
        self._rules: dict[str, LabelRule] = {}
        self._default: LabelRule = LabelRule(label="__default__", enabled=False)

        # État runtime
        self._last_trigger: dict[str, float] = {}
        self._first_seen:   dict[str, float] = {}   # pour min_duration

        self.reload()

    # ── Chargement config ─────────────────────────────────────────
    def reload(self) -> None:
        if not self.config_path.exists():
            print(f"[rules] Config introuvable : {self.config_path} — règles vides")
            return
        raw = self._load_file()
        rules_raw = raw.get("rules", {})
        default_raw = raw.get("default", {})

        self._default = self._parse_rule("__default__", default_raw)
        self._rules = {
            label: self._parse_rule(label, cfg)
            for label, cfg in rules_raw.items()
        }
        print(f"[rules] {len(self._rules)} règles chargées depuis {self.config_path}")

    def _load_file(self) -> dict:
        with open(self.config_path, encoding="utf-8") as fh:
            if _YAML:
                return yaml.safe_load(fh) or {}
            return {}  # fallback minimal

    @staticmethod
    def _parse_rule(label: str, cfg: dict) -> LabelRule:
        return LabelRule(
            label        = label,
            enabled      = cfg.get("enabled", True),
            cooldown     = float(cfg.get("cooldown", 5.0)),
            min_duration = float(cfg.get("min_duration", 0.0)),
            actions      = [ActionDef.from_dict(a) for a in cfg.get("actions", [])],
        )

    # ── API principale ────────────────────────────────────────────
    def get_rule(self, label: str) -> LabelRule:
        return self._rules.get(label.lower(), self._default)

    def should_trigger(self, label: str, now: float | None = None) -> bool:
        """
        Retourne True si le label doit déclencher des actions.
        Gère enabled, cooldown et min_duration.
        """
        label = label.lower()
        now = time.time() if now is None else now
        rule = self.get_rule(label)

        if not rule.enabled:
            return False

        # Cooldown
        if now - self._last_trigger.get(label, 0.0) < rule.cooldown:
            return False

        # min_duration : enregistre le premier instant de détection
        if rule.min_duration > 0:
            if label not in self._first_seen:
                self._first_seen[label] = now
                return False
            elapsed = now - self._first_seen[label]
            if elapsed < rule.min_duration:
                return False

        return True

    def mark_triggered(self, label: str, now: float | None = None) -> None:
        """Appelé après que les actions ont été exécutées."""
        label = label.lower()
        now = time.time() if now is None else now
        self._last_trigger[label] = now
        self._first_seen.pop(label, None)

    def reset_seen(self, label: str) -> None:
        """Appelé quand le label disparaît de la frame (détection perdue)."""
        self._first_seen.pop(label.lower(), None)

    def get_actions(self, label: str) -> list[ActionDef]:
        return self.get_rule(label.lower()).actions

    # ── Infos debug ───────────────────────────────────────────────
    def summary(self) -> str:
        active = [l for l, r in self._rules.items() if r.enabled]
        return f"rules: {len(active)} actives / {len(self._rules)} totales"
