"""One persistent ON/OFF preference shared by the local CLI and MQTT switch.

Only the existing release checker triggers installation. This preference does
not add a timer, change host configuration, or restart the monitoring agent.
"""
from __future__ import annotations

import fcntl
import os
from pathlib import Path

from .state_store import StateStore, StateStoreError


class AutoUpdatePreference:
    def __init__(self, state_dir: Path) -> None:
        self.store = StateStore(state_dir / "auto_update.json")

    def enabled(self) -> bool:
        value = self.store.load().get("enabled", False)
        if not isinstance(value, bool):
            raise StateStoreError("invalid auto-update preference")
        return value

    def set(self, enabled: bool) -> bool:
        if not isinstance(enabled, bool):
            raise ValueError("auto-update requires a boolean")
        self.store.path.parent.mkdir(parents=True, exist_ok=True)
        # CLI and MQTT can change this one preference concurrently. Serialize
        # writers because StateStore uses a fixed atomic temporary filename.
        lock_fd = os.open(self.store.path.with_name("auto_update.lock"),
                          os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(lock_fd, "r+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if self.enabled() == enabled:
                return False
            self.store.save({"enabled": enabled})
            return True
