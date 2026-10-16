"""Persistent household-wide detection methods, independent of notification switches."""
from __future__ import annotations

import json
from pathlib import Path

from .storage import atomic_json

DEFAULTS = {"ping": False, "arp": True}
PROBE_KEYS = tuple(DEFAULTS)


class ProbeSelection:
    def __init__(self, path: str):
        self.path = path
        try:
            saved = json.loads(Path(path).read_text(encoding="utf-8"))
        except FileNotFoundError:
            saved = None
        if saved is None:
            self.enabled = dict(DEFAULTS)
        else:
            if (not isinstance(saved, dict) or saved.get("schema_version") != 1
                    or not isinstance(saved.get("enabled"), dict)
                    or set(saved["enabled"]) != set(DEFAULTS)
                    or any(type(saved["enabled"][key]) is not bool for key in DEFAULTS)):
                raise ValueError("Invalid saved detection method preferences")
            self.enabled = dict(saved["enabled"])
        self.save()

    def save(self) -> None:
        atomic_json(self.path, {"schema_version": 1, "enabled": self.enabled})

    def change(self, key: str, requested: str) -> bool:
        if key not in DEFAULTS or requested not in ("ON", "OFF"):
            raise ValueError("Invalid detection method command")
        desired = requested == "ON"
        if self.enabled[key] is desired:
            return False
        old = self.enabled[key]
        self.enabled[key] = desired
        try:
            self.save()
        except OSError:
            self.enabled[key] = old
            raise
        return True

    def mqtt_state(self, key: str) -> str:
        return "ON" if self.enabled[key] else "OFF"
