"""Opt-in, bounded read-only NUT trace. Never participates in UPS/FSD decisions."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable

from .config import UpsConfig
from .state_store import StateStore
from .ups_nut import UpsSnapshot, read_ups


_LOG = logging.getLogger(__name__)
MAX_DEBUG_SECONDS = 72 * 3600
SAMPLE_SECONDS = 2.0
MAX_FILE_BYTES = 10 * 1024 * 1024
BACKUP_COUNT = 5


class _PrivateRotatingHandler(RotatingFileHandler):
    """Create both active and rotated replacement files with mode 0600."""

    def _open(self):
        flags = os.O_CREAT | os.O_APPEND | os.O_WRONLY
        fd = os.open(self.baseFilename, flags, 0o600)
        return os.fdopen(fd, self.mode, encoding=self.encoding)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _snapshot_fields(snapshot: UpsSnapshot) -> dict[str, object]:
    result: dict[str, object] = {
        "status_raw": snapshot.status_raw,
        "status_tokens": list(snapshot.status_tokens),
        "charger_status": snapshot.battery_charger_status,
        "on_battery": snapshot.on_battery,
        "line_power": snapshot.line_power,
    }
    for field in (
        "battery_charge_percent",
        "runtime_seconds",
        "battery_voltage_v",
        "battery_nominal_voltage_v",
        "low_charge_percent",
        "low_runtime_seconds",
        "warning_charge_percent",
        "load_percent",
        "nominal_real_power_w",
        "input_voltage_v",
        "output_voltage_v",
        "input_transfer_high_v",
        "input_transfer_low_v",
    ):
        result[field] = getattr(snapshot, field, None)
    for raw_field in ("ups.alarm", "ups.test.result"):
        result[raw_field] = snapshot.raw.get(raw_field)
    return result


class UpsDebugRecorder:
    """A separate diagnostic reader, strictly isolated from the operational UPS path.

    Enablement is explicit and expires at an absolute UTC deadline, even if the
    agent restarts or Home Assistant/MQTT is unavailable. OFF is the default.
    """

    def __init__(
        self,
        state_dir: Path,
        ups_config: UpsConfig | None,
        *,
        reader: Callable[[UpsConfig], UpsSnapshot] = read_ups,
        now: Callable[[], datetime] = _utc_now,
        sample_seconds: float = SAMPLE_SECONDS,
    ) -> None:
        self.path = state_dir / "dh_ups_debug.log"
        self._store = StateStore(state_dir / "ups_debug_state.json")
        self._reader = reader
        self._now = now
        self._interval = sample_seconds
        self._config = ups_config
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._enabled = False
        self._expires_at: datetime | None = None
        self._handler = _PrivateRotatingHandler(
            self.path,
            maxBytes=MAX_FILE_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
            delay=True,
        )
        self._handler.setFormatter(logging.Formatter("%(message)s"))
        self._last_error_logged = 0.0
        try:
            saved = self._store.load()
            expiry = saved.get("expires_at")
            if saved.get("enabled") is True and isinstance(expiry, str):
                parsed = datetime.fromisoformat(expiry)
                if parsed.tzinfo is not None and parsed > self._now():
                    self._enabled = True
                    self._expires_at = parsed
                else:
                    self._save_state_locked()
        except (ValueError, TypeError, OSError, RuntimeError) as exc:
            _LOG.warning("UPS debug state unreadable; logging stays OFF: %s", type(exc).__name__)
        self._worker = threading.Thread(
            target=self._loop, name="dh-pve-ups-debug", daemon=True
        )
        self._worker.start()

    def _save_state_locked(self) -> None:
        self._store.save({
            "schema_version": 1,
            "enabled": self._enabled,
            "expires_at": self._expires_at.isoformat() if self._expires_at else None,
        })

    def _emit(self, kind: str, fields: dict[str, object], *, sync: bool = False) -> None:
        payload = {
            "observed_at": self._now().isoformat(),
            "kind": kind,
            **fields,
        }
        try:
            with self._lock:
                record = logging.LogRecord(
                    "dh_pve_ups_debug", logging.INFO, __file__, 0,
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    (), None,
                )
                self._handler.emit(record)
                if sync and self._handler.stream is not None:
                    self._handler.flush()
                    os.fsync(self._handler.stream.fileno())
        except Exception as exc:
            # Debugging must NEVER prevent NUT/FSD or the agent from operating.
            now = time.monotonic()
            if now - self._last_error_logged > 60:
                _LOG.warning("UPS debug write failed (ignored): %s", type(exc).__name__)
                self._last_error_logged = now

    def _expire_locked(self) -> bool:
        if not self._enabled or self._expires_at is None:
            return False
        if self._now() < self._expires_at:
            return False
        self._enabled = False
        self._expires_at = None
        try:
            self._save_state_locked()
        except Exception as exc:
            _LOG.warning("Could not persist UPS debug auto-disable: %s", type(exc).__name__)
        self._emit("auto_disabled", {"reason": "72h_expired"}, sync=True)
        return True

    def enabled(self) -> bool:
        with self._lock:
            self._expire_locked()
            return self._enabled

    def set_enabled(self, enabled: bool) -> bool:
        if not isinstance(enabled, bool):
            raise TypeError("UPS debug command must be boolean")
        with self._lock:
            self._expire_locked()
            if enabled and self._config is None:
                return False
            old_state = (self._enabled, self._expires_at)
            self._enabled = enabled
            # Each intentional ON grants exactly 72h, never an unlimited timer.
            self._expires_at = self._now() + timedelta(seconds=MAX_DEBUG_SECONDS) if enabled else None
            try:
                self._save_state_locked()
            except Exception as exc:
                self._enabled, self._expires_at = old_state
                _LOG.warning("UPS debug setting not persisted: %s", type(exc).__name__)
                return self._enabled
            self._emit(
                "enabled" if enabled else "disabled",
                {"expires_at": self._expires_at.isoformat() if self._expires_at else None},
                sync=True,
            )
            self._wake.set()
            return self._enabled

    def set_config(self, config: UpsConfig | None) -> None:
        with self._lock:
            self._config = config
            self._wake.set()

    def record_software_fsd(self, reason: str, snapshot: UpsSnapshot | None, policy: object, budget: object) -> None:
        if not self.enabled():
            return
        fields: dict[str, object] = {
            "reason": reason,
            "charge_threshold_percent": getattr(policy, "shutdown_battery_charge_threshold_percent", None),
            "runtime_reserve_seconds": getattr(policy, "runtime_reserve_seconds", None),
            "shutdown_budget_seconds": getattr(budget, "shutdown_budget_seconds", None),
        }
        if snapshot is not None:
            fields.update(_snapshot_fields(snapshot))
        self._emit("software_fsd_intent", fields, sync=True)

    def _loop(self) -> None:
        previous: dict[str, object] | None = None
        while not self._stop.is_set():
            with self._lock:
                self._expire_locked()
                active = self._enabled
                config = self._config
            if not active or config is None:
                previous = None
                self._wake.wait(1.0)
                self._wake.clear()
                continue

            started = time.monotonic()
            try:
                snapshot = self._reader(config)
                fields = _snapshot_fields(snapshot)
                tokens = set(snapshot.status_tokens)
                urgent = bool(tokens & {"OB", "LB", "FSD"})
                if previous is not None:
                    urgent = urgent or (
                        fields["status_raw"] != previous.get("status_raw")
                    )
                    charge = fields.get("battery_charge_percent")
                    earlier = previous.get("battery_charge_percent")
                    if isinstance(charge, (int, float)) and isinstance(earlier, (int, float)):
                        urgent = urgent or abs(charge - earlier) >= 15
                self._emit("nut_sample", fields, sync=urgent)
                previous = fields
            except Exception as exc:
                self._emit(
                    "nut_read_error",
                    {"error_type": type(exc).__name__, "error": str(exc)[:240]},
                    sync=True,
                )
                previous = None

            self._wake.wait(max(0.0, self._interval - (time.monotonic() - started)))
            self._wake.clear()

    def close(self) -> None:
        self._stop.set()
        self._wake.set()
        self._worker.join(timeout=5)
        with self._lock:
            self._handler.close()
