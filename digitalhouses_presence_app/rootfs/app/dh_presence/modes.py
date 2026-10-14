"""Live MQTT Select mode, persisted under /data.

Configuration becomes authoritative when it actually changes, otherwise the
last UI selection is restored after restart/update. Invalid saved state is fatal.
"""
from __future__ import annotations

import json
from pathlib import Path
from .core import Mode
from .storage import atomic_json


class ModeSelection:
    def __init__(self, path: str, configured: Mode):
        self.path = path
        self.configured = Mode(configured)
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except FileNotFoundError:
            raw = None
        if raw is not None:
            if not isinstance(raw, dict) or raw.get("schema_version") != 1:
                raise ValueError("Invalid saved mode state")
            old_config = Mode(raw["configured_mode"])
            selected = Mode(raw["selected_mode"])
            self.selected = selected if old_config == self.configured else self.configured
        else:
            self.selected = self.configured
        self.save()

    def save(self):
        atomic_json(self.path, {"schema_version": 1,
                               "configured_mode": self.configured.value,
                               "selected_mode": self.selected.value})

    def change(self, requested: str) -> bool:
        """Validated MQTT command changes mode, but only a real change writes."""
        mode = Mode(requested)
        if mode is self.selected:
            return False
        self.selected = mode
        self.save()
        return True
