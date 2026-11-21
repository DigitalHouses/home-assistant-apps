"""Small atomic local state store. No database or auxiliary service."""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path


class StateStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> dict:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                return value
        except FileNotFoundError:
            return {}
        except (ValueError, OSError):
            pass
        raise ValueError(f"invalid agent state: {self.path}")

    def save(self, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix="." + self.path.name + ".", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                os.fchmod(handle.fileno(), 0o600)
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)


# Display-only Home Assistant MQTT Number settings; not part of the agent INI.
VIEW_LIMIT_RANGES = {"backup_groups": (1, 80), "task_events": (1, 50)}


class ViewLimits:
    def __init__(self, store: StateStore | None = None):
        self.store = store
        self.lock = threading.Lock()
        saved = store.load() if store else {}
        self.values = {}
        for key, (low, high) in VIEW_LIMIT_RANGES.items():
            value = saved.get(key, 10)
            self.values[key] = value if type(value) is int and low <= value <= high else 10

    def snapshot(self) -> dict:
        with self.lock:
            return dict(self.values)

    def update(self, key: str, value: int) -> dict:
        if key not in VIEW_LIMIT_RANGES:
            raise ValueError("invalid view limit key")
        low, high = VIEW_LIMIT_RANGES[key]
        if type(value) is not int or not low <= value <= high:
            raise ValueError("invalid view limit value")
        with self.lock:
            if self.values[key] != value:
                updated = {**self.values, key: value}
                if self.store:
                    self.store.save(updated)
                self.values = updated
            return dict(self.values)
