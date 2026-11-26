"""Nonblocking MQTT/HOME guide for UPS commissioning.

All potentially privileged work is done by a single dedicated systemd oneshot;
the normal agent keeps monitoring the PVE host in its protected service.
"""
from __future__ import annotations

import logging
import subprocess
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from .config import load_config
from .state_store import StateStore
from .ups_setup import VALID_STAGES, driver_options, setup_snapshot

LOG = logging.getLogger(__name__)
REFRESH_SECONDS = 120.0


def _start_setup_unit(stage: str) -> None:
    if stage not in VALID_STAGES:
        raise ValueError("unsupported UPS setup stage")
    try:
        result = subprocess.run(
            ["systemctl", "start", f"digitalhouses_pve_agent-ups-setup@{stage}.service"],
            capture_output=True, text=True, check=False, timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("NUT setup service did not complete") from exc
    if result.returncode != 0:
        raise RuntimeError("NUT setup service failed; inspect its operation status")


class UpsSetupManager:
    def __init__(self, bridge, *, config_path: Path, state_dir: Path,
                 now=time.monotonic, inspect=setup_snapshot, apply=_start_setup_unit) -> None:
        self.bridge = bridge
        self.config_path = config_path
        self.state_dir = state_dir
        self.now = now
        self.inspect = inspect
        self.apply = apply
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dh-ups-setup")
        self.future: Future | None = None
        self.kind: str | None = None
        self.stage: str | None = None
        self.last_inspected = -REFRESH_SECONDS
        self.latest: dict[str, object] = {}
        self.force_refresh = True
        self.operation: dict[str, str] = {"state": "idle", "stage": "", "message": ""}

    def close(self) -> None:
        self.worker.shutdown(wait=False, cancel_futures=False)

    def _inspect(self) -> dict[str, object]:
        return self.inspect(load_config(self.config_path), state_dir=self.state_dir)

    def _publish(self) -> None:
        payload = dict(self.latest)
        payload["operation"] = dict(self.operation)
        self.bridge.publish_ups_setup_state(payload)

    def tick(self) -> bool:
        """Nonblocking step; return True only when a completed PRIMARY setup needs restart."""
        current = self.now()
        restart_required = False
        while not self.bridge.ups_setup_driver_updates.empty():
            driver = self.bridge.ups_setup_driver_updates.get_nowait()
            if driver not in driver_options():
                continue
            StateStore(self.state_dir / "ups_setup_driver.json").save({"driver": driver})
            self.force_refresh = True

        if self.future is not None and self.future.done():
            previous, stage, future = self.kind, self.stage, self.future
            self.future = None
            self.kind = None
            self.stage = None
            try:
                response = future.result()
            except Exception as exc:
                LOG.warning("UPS setup %s: %s", stage, exc)
                try:
                    persisted = StateStore(self.state_dir / "ups_setup_operation.json").load()
                    message = str(persisted.get("message") or "Невозможно выполнить операцию")
                except Exception:
                    message = "Невозможно выполнить операцию"
                self.operation = {"state": "error", "stage": stage or "",
                                  "message": message[:200]}
            else:
                if previous == "apply":
                    self.operation = {"state": "success", "stage": stage or "",
                                      "message": "Этап успешно выполнен"}
                    if stage in ("driver", "primary"):
                        self.bridge.ups_scan_requested.set()
                    if stage in ("install", "primary"):
                        restart_required = True
                elif isinstance(response, dict):
                    self.latest = response
                    self.last_inspected = current
            self.force_refresh = True
            self._publish()

        requested: str | None = None
        while not self.bridge.ups_setup_requests.empty():
            stage = self.bridge.ups_setup_requests.get_nowait()
            if stage in VALID_STAGES and requested is None:
                requested = stage
        if requested is not None and self.future is None:
            allowed = (self.latest.get("actions") or {}).get(requested) is True
            if not allowed:
                self.operation = {"state": "error", "stage": requested,
                                  "message": "Недоступен этап или не выполнены его условия"}
                self._publish()
            else:
                self.operation = {"state": "running", "stage": requested, "message": ""}
                self._publish()
                self.future = self.worker.submit(self.apply, requested)
                self.kind = "apply"
                self.stage = requested

        if (self.future is None and (self.force_refresh or
                                     current - self.last_inspected >= REFRESH_SECONDS)):
            self.force_refresh = False
            self.future = self.worker.submit(self._inspect)
            self.kind = "inspect"
        return restart_required
