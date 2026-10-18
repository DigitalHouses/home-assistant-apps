"""Persistent per-source and per-zone notification preferences; notifications never gate events."""
from __future__ import annotations

import json
from pathlib import Path
from .storage import atomic_json
from .zones import zone_key

DEFAULTS = {"gps": False, "wifi": False}
NOTIFICATION_KEYS = tuple(DEFAULTS)


class NotificationSelection:
    def __init__(self, path: str):
        self.path = path
        try:
            saved = json.loads(Path(path).read_text(encoding="utf-8"))
        except FileNotFoundError:
            saved = None
        self.zones: dict[str, bool] = {}
        if saved is None:
            self.enabled = dict(DEFAULTS)
        elif isinstance(saved, dict) and saved.get("schema_version") == 1:
            old = saved.get("enabled")
            if (not isinstance(old, dict) or set(old) != {"presence", "gps", "wifi"}
                    or any(type(v) is not bool for v in old.values())):
                raise ValueError("Invalid legacy notification preferences")
            self.enabled = {key: old[key] for key in DEFAULTS}
        elif isinstance(saved, dict) and saved.get("schema_version") == 2:
            self.enabled = saved.get("enabled")
            self.zones = saved.get("zones")
            if (not isinstance(self.enabled, dict) or set(self.enabled) != set(DEFAULTS)
                    or any(type(v) is not bool for v in self.enabled.values())
                    or not isinstance(self.zones, dict)
                    or any(not isinstance(k, str) or len(k) != 16 or type(v) is not bool
                           for k, v in self.zones.items())):
                raise ValueError("Invalid notification preferences")
        else:
            raise ValueError("Invalid notification preferences")
        self.save()

    def save(self):
        atomic_json(self.path, {"schema_version": 2, "enabled": self.enabled, "zones": self.zones})

    def sync_zones(self, zones: dict[str, str]) -> bool:
        # Removed zones lose their preference. A re-created zone must start OFF.
        active = {zone_key(entity_id) for entity_id in zones}
        changed = False
        for key in list(self.zones):
            if key not in active:
                del self.zones[key]
                changed = True
        for key in active:
            if key not in self.zones:
                self.zones[key] = False
                changed = True
        if changed:
            self.save()
        return changed

    def change(self, key: str, requested: str) -> bool:
        if requested not in ("ON", "OFF"):
            raise ValueError("Invalid MQTT notification switch command")
        if key in DEFAULTS:
            mapping = self.enabled
        elif key.startswith("zones/") and key[6:] in self.zones:
            mapping = self.zones
            key = key[6:]
        else:
            raise ValueError("Unknown notification switch")
        desired = requested == "ON"
        if mapping[key] is desired:
            return False
        previous = mapping[key]
        mapping[key] = desired
        try:
            self.save()
        except OSError:
            mapping[key] = previous
            raise
        return True

    def mqtt_state(self, key: str) -> str:
        if key in self.enabled:
            return "ON" if self.enabled[key] else "OFF"
        if key.startswith("zones/") and key[6:] in self.zones:
            return "ON" if self.zones[key[6:]] else "OFF"
        raise ValueError("Unknown notification switch")
