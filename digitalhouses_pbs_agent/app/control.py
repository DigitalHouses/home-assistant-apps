"""PBS Agent user operations, matching DigitalHouses Linux Agent card contract.

The collector owns Refresh/check; an independent systemd oneshot handles
self-replacement and restart. All visible state is runtime-owned and retained.
"""
from __future__ import annotations

import queue
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .mqtt import _read_version
from .releases import latest_release, stable_version
from .state import StateStore

WORKER_SERVICE = "digitalhouses_pbs_agent-control.service"


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def blank_operation() -> dict:
    return {"state": "idle", "started_at": None, "finished_at": None,
            "duration_seconds": None, "error": None}


class Controller:
    def __init__(self, state_dir: Path, publisher) -> None:
        self.publisher = publisher
        self.store = StateStore(state_dir / "control.json")
        self.worker = StateStore(state_dir / "control_worker.json")
        self.request = StateStore(state_dir / "control_request.json")
        self.preference = StateStore(state_dir / "auto_update.json")
        self.auto_update = self.preference.load().get("enabled") is True
        saved = self.store.load()
        self.card = saved.get("card") or {**blank_operation(), "operation": None}
        self.refresh = saved.get("refresh") or blank_operation()
        self.last_refresh = saved.get("last_refresh")
        self.last_collection_at = saved.get("last_collection_at")
        self.latest_version = saved.get("latest_version") or "unknown"
        # A cached version comparison is not fresh proof after any restart.
        self.available = None
        self.checked_at = saved.get("checked_at")
        self.update_status = saved.get("update_status", "idle")
        self._busy_start: float | None = None
        self._checking: bool = False
        self._manual_check_waiting: bool = False
        self._results: queue.SimpleQueue = queue.SimpleQueue()
        self._last_payload: dict | None = None
        if self.card.get("state") == "running":
            if self.card.get("operation") not in ("install", "restart"):
                self.finish(self.card.get("operation"), "Прервано перезапуском агента")
        if self.refresh.get("state") == "updating":
            self.refresh = {**self.refresh, "state": "error", "finished_at": stamp(),
                            "error": "Обновление данных прервано перезапуском"}
        self.publish()

    def payload(self) -> dict:
        return {
            "card": {k: v for k, v in self.card.items() if k != "request_id"},
            "refresh": self.refresh,
            "last_refresh": self.last_refresh,
            "last_collection_at": self.last_collection_at,
            "latest_version": self.latest_version,
            "update_available": self.available,
            "update_status": self.update_status,
            "checked_at": self.checked_at,
            "auto_update": self.auto_update,
        }

    def publish(self) -> None:
        payload = self.payload()
        if self._last_payload != payload:
            self.store.save({**payload, "card": self.card})
            self.publisher.control(payload)
            self._last_payload = payload

    def begin(self, operation: str) -> bool:
        if self.card["state"] == "running":
            return False
        # Freeze the version transition when install begins: automatic update
        # clears update_available while the worker runs, but the UI must
        # continue to show the exact from -> to versions.
        self.card = {
            **blank_operation(), "state": "running",
            "operation": operation, "started_at": stamp(),
            "from_version": _read_version() if operation == "install" else None,
            "target_version": self.latest_version if operation == "install" else None,
        }
        self._busy_start = time.monotonic()
        if operation == "refresh":
            self.refresh = {**blank_operation(), "state": "updating",
                            "started_at": self.card["started_at"]}
        if operation == "check":
            self.update_status = "checking"
        self.publish()
        return True

    def finish(self, operation: str | None, error: str | None = None,
               duration_seconds: float | None = None) -> None:
        if self.card.get("state") != "running" or self.card.get("operation") != operation:
            return
        elapsed = (max(0, time.monotonic() - self._busy_start)
                   if self._busy_start is not None
                   else max(0, (datetime.now(timezone.utc) -
                                datetime.fromisoformat(self.card["started_at"])).total_seconds()))
        duration = (duration_seconds if isinstance(duration_seconds, (int, float))
                    and 0 <= duration_seconds < 100000 else elapsed)
        self.card.update(state="error" if error else "success",
                         finished_at=stamp(), duration_seconds=round(duration, 2),
                         error=error[:160] if error else None)
        if operation == "refresh":
            self.refresh = {k: self.card.get(k) for k in
                            ("started_at", "finished_at", "duration_seconds", "error")}
            self.refresh["state"] = "error" if error else "idle"
            if not error:
                self.last_refresh = self.card["finished_at"]
        if operation == "check":
            self.update_status = "error" if error else "idle"
        self._busy_start = None
        self.publish()

    def start_check(self, manual: bool = True) -> bool:
        if self._checking:
            if manual and self.begin("check"):
                self._manual_check_waiting = True
                return True
            return False
        if manual and not self.begin("check"):
            return False
        if not manual and self.card["state"] == "running":
            return False
        self._checking = True

        def check() -> None:
            try:
                tag, version = latest_release()
                self._results.put((tag, version, None, manual))
            except Exception as exc:
                self._results.put((None, None, type(exc).__name__, manual))
        threading.Thread(target=check, name="pbs-release-check", daemon=True).start()
        return True

    def set_auto_update(self, enabled: bool) -> bool:
        if type(enabled) is not bool:
            return False
        if enabled == self.auto_update:
            return False
        self.preference.save({"enabled": enabled})
        self.auto_update = enabled
        self.publish()
        if enabled and self.card["state"] != "running":
            if self.available is True:
                self.queue_worker("install")
            else:
                self.start_check(manual=False)
        return True

    def queue_worker(self, action: str) -> bool:
        if action not in ("install", "restart") or not self.begin(action):
            return False
        if action == "install" and self.available is not True:
            self.finish(action, "Нет подтверждённой новой стабильной версии")
            return False
        transaction = self.card["started_at"]
        self.card["request_id"] = transaction
        self.request.save({"request_id": transaction, "action": action})
        self.worker.save({"request_id": transaction, "state": "queued"})
        self.store.save({**self.payload(), "card": self.card})
        self.publish()
        try:
            result = subprocess.run(
                ["systemctl", "start", "--no-block", WORKER_SERVICE],
                capture_output=True, timeout=15, check=False,
            )
            if result.returncode:
                raise RuntimeError("Не удалось запустить systemd-обработчик операции")
        except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
            self.finish(action, str(exc)[:160])
            return False
        return True

    def tick(self) -> None:
        requested_auto = self.preference.load().get("enabled") is True
        if requested_auto != self.auto_update:
            self.auto_update = requested_auto
            self.publish()
            if requested_auto and self.card["state"] != "running":
                if self.available is True:
                    self.queue_worker("install")
                else:
                    self.start_check(manual=False)
        while not self._results.empty():
            tag, version, error, manual = self._results.get_nowait()
            manual = manual or self._manual_check_waiting
            self._manual_check_waiting = False
            self._checking = False
            self.checked_at = stamp()
            self.latest_version = version or "unknown"
            self.available = (
                stable_version(version) > stable_version(_read_version())
                if version else None
            )
            if manual:
                self.finish("check", "Ошибка проверки GitHub Releases" if error else None)
            else:
                self.publish()
                if self.available is True and self.auto_update:
                    self.queue_worker("install")

        if self.card["state"] == "running" and self.card["operation"] in ("install", "restart"):
            record = self.worker.load()
            if record.get("request_id") == self.card.get("request_id"):
                if record.get("state") in ("completed", "error"):
                    error = record.get("error") or (
                        "Операция не выполнена" if record["state"] == "error" else None
                    )
                    if self.card["operation"] == "install" and not error:
                        target = self.card.get("target_version")
                        installed = _read_version()
                        try:
                            correct_version = (
                                stable_version(installed) >= stable_version(target)
                                if target and target != "unknown" else True
                            )
                        except (ValueError, TypeError):
                            correct_version = False
                        if not correct_version:
                            error = (
                                f"Установлена v{installed}, ожидалась v{target}"
                            )
                        else:
                            self.available = False
                    self.finish(
                        self.card["operation"], error,
                        record.get("duration_seconds"),
                    )
            if self.card["state"] == "running" and self.card.get("started_at"):
                # Queued workers which never started must not stay stuck forever.
                age = (datetime.now(timezone.utc) -
                       datetime.fromisoformat(self.card["started_at"])).total_seconds()
                if age > 1200:
                    self.finish(self.card["operation"], "Нет результата системной операции")
                elif age > 45 and record.get("state") == "queued":
                    try:
                        active = subprocess.run(
                            ["systemctl", "is-active", "--quiet", WORKER_SERVICE],
                            timeout=5, capture_output=True, check=False,
                        ).returncode == 0
                    except (OSError, subprocess.SubprocessError):
                        active = False
                    if not active:
                        self.finish(self.card["operation"], "Systemd-обработчик не запустился")

        if self.card["state"] == "success":
            finished_at = self.card["finished_at"]
            if finished_at and (datetime.now(timezone.utc) -
                                datetime.fromisoformat(finished_at)).total_seconds() >= 5:
                self.card = {**blank_operation(), "operation": None}
                self.publish()

    def collection_at(self, value: str | None) -> None:
        if value != self.last_collection_at:
            self.last_collection_at = value
            self.publish()
