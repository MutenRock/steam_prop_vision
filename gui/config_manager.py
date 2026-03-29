# -*- coding: utf-8 -*-
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict
import os, json

@dataclass
class LoadedConfig:
    folder: str
    data: Dict[str, Any]

def load_config_folder(folder: str) -> LoadedConfig:
    cfg_path = os.path.join(folder, "config.json")
    if not os.path.isfile(cfg_path):
        raise FileNotFoundError(f"config.json not found in {folder}")
    with open(cfg_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return LoadedConfig(folder=folder, data=data)

def get_plaques_folder(folder: str) -> str:
    return os.path.join(folder, "plaques")
