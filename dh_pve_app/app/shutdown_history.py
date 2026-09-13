from __future__ import annotations

import re
import subprocess
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .state_store import StateStore
from .ups_nut import UpsSnapshot


HISTORY_LIMIT = 50
PUBLISHED_HISTORY_LIMIT = 10

_TIMESTAMP_RE = re.compile(r"^(?P<ts>\S+)")
_START_RE = re.compile(
    r"\bStopping\s+(?P<kind>VM|CT)\s+(?P<id>\d+)\s+"
    r"\(timeout\s*=\s*(?P<timeout>\d+)\s+seconds\)",
    re.IGNORECASE,
)
_TIMEOUT_RE = re.compile(
    r"\b(?P<kind>VM|CT)\s+(?P<id>\d+).*?(?:got timeout|timed out)",
    re.IGNORECASE,
)
_END_TASK_RE = re.compile(
    r"\bend task UPID:.*?:(?P<type>qmshutdown|vzshutdown):(?P<id>\d+):",
    re.IGNORECASE,
)
_SIMPLE_END_RE = re.compile(
    r"\b(?P<kind>VM|CT)\s*(?P<id>\d+).*?task ended",
    re.IGNORECASE,
)
_ALL_STOPPED_RE = re.compile(r"\ball VMs and CTs stopped\b", re.IGNORECASE)
_CLEAN_MARKERS = (
    "reached target shutdown.target",
    "reached target system power off",
    "systemd-shutdown",
    "system is powering down",
    "powering off",
)


def _parse_timestamp(line: str) -> datetime | None:
    match = _TIMESTAMP_RE.match(line.strip())
    if match is None:
        return None
    raw = match.group("ts")
    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return None
    return value


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _seconds(start: datetime | None, end: datetime | None) -> int | None:
    if start is None or end is None:
        return None
    return max(0, int(round((end - start).total_seconds())))


def _guest_kind(token: str) -> str:
    return "vm" if token.casefold() == "vm" else "lxc"


def parse_guest_shutdown_journal(text: str) -> dict[str, Any]:
    records: dict[tuple[str, str], dict[str, Any]] = {}
    first_started: datetime | None = None
    last_timestamp: datetime | None = None
    all_stopped_at: datetime | None = None
    clean_shutdown = False

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        timestamp = _parse_timestamp(line)
        if timestamp is not None:
            last_timestamp = timestamp

        lowered = line.casefold()
        if any(marker in lowered for marker in _CLEAN_MARKERS):
            clean_shutdown = True

        start = _START_RE.search(line)
        if start is not None:
            kind = _guest_kind(start.group("kind"))
            guest_id = start.group("id")
            timeout = int(start.group("timeout"))
            key = (kind, guest_id)
            item = records.setdefault(
                key,
                {
                    "kind": kind,
                    "guest_id": guest_id,
                    "timeout_seconds": timeout,
                    "started_at": None,
                    "finished_at": None,
                    "duration_seconds": None,
                    "timeout_ratio": None,
                    "result": "unknown",
                    "forced": False,
                },
            )
            item["timeout_seconds"] = timeout
            if item["started_at"] is None and timestamp is not None:
                item["started_at"] = timestamp.isoformat()
                if first_started is None or timestamp < first_started:
                    first_started = timestamp
            continue

        timeout_match = _TIMEOUT_RE.search(line)
        if timeout_match is not None:
            kind = _guest_kind(timeout_match.group("kind"))
            guest_id = timeout_match.group("id")
            key = (kind, guest_id)
            item = records.setdefault(
                key,
                {
                    "kind": kind,
                    "guest_id": guest_id,
                    "timeout_seconds": None,
                    "started_at": None,
                    "finished_at": None,
                    "duration_seconds": None,
                    "timeout_ratio": None,
                    "result": "unknown",
                    "forced": False,
                },
            )
            item["result"] = "timeout"
            item["forced"] = True
            continue

        end_match = _END_TASK_RE.search(line)
        if end_match is not None:
            kind = "vm" if end_match.group("type").casefold() == "qmshutdown" else "lxc"
            guest_id = end_match.group("id")
            key = (kind, guest_id)
            item = records.setdefault(
                key,
                {
                    "kind": kind,
                    "guest_id": guest_id,
                    "timeout_seconds": None,
                    "started_at": None,
                    "finished_at": None,
                    "duration_seconds": None,
                    "timeout_ratio": None,
                    "result": "unknown",
                    "forced": False,
                },
            )
            if timestamp is not None:
                item["finished_at"] = timestamp.isoformat()
            if item["result"] == "unknown":
                item["result"] = "clean"
            continue

        simple_end = _SIMPLE_END_RE.search(line)
        if simple_end is not None:
            kind = _guest_kind(simple_end.group("kind"))
            guest_id = simple_end.group("id")
            key = (kind, guest_id)
            item = records.setdefault(
                key,
                {
                    "kind": kind,
                    "guest_id": guest_id,
                    "timeout_seconds": None,
                    "started_at": None,
                    "finished_at": None,
                    "duration_seconds": None,
                    "timeout_ratio": None,
                    "result": "unknown",
                    "forced": False,
                },
            )
            if timestamp is not None:
                item["finished_at"] = timestamp.isoformat()
            if item["result"] == "unknown":
                item["result"] = "clean"
            continue

        if _ALL_STOPPED_RE.search(line) and timestamp is not None:
            all_stopped_at = timestamp

    guests: dict[str, dict[str, dict[str, Any]]] = {"vm": {}, "lxc": {}}
    latest_finished: datetime | None = None
    for (kind, guest_id), raw in sorted(records.items()):
        item = dict(raw)
        started = None
        finished = None
        if isinstance(item.get("started_at"), str):
            try:
                started = datetime.fromisoformat(item["started_at"])
            except ValueError:
                started = None
        if isinstance(item.get("finished_at"), str):
            try:
                finished = datetime.fromisoformat(item["finished_at"])
            except ValueError:
                finished = None
        duration = _seconds(started, finished)
        item["duration_seconds"] = duration
        timeout = item.get("timeout_seconds")
        if duration is not None and isinstance(timeout, int) and timeout > 0:
            item["timeout_ratio"] = round(duration / timeout, 3)
        if finished is not None and (latest_finished is None or finished > latest_finished):
            latest_finished = finished
        guests[kind][guest_id] = item

    stop_boundary = all_stopped_at or latest_finished
    total = _seconds(first_started, stop_boundary)
    return {
        "guests": guests,
        "all_guests_stopped_at": _iso(all_stopped_at),
        "guest_shutdown_total_seconds": total,
        "clean_shutdown": clean_shutdown,
        "shutdown_at": _iso(last_timestamp),
    }


def classify_previous_shutdown(
    *,
    clean_shutdown: bool,
    fsd_reason: str | None,
) -> tuple[str, str]:
    if fsd_reason in {"on_battery_fsd", "low_battery_fsd"}:
        return "ups_power", fsd_reason
    if clean_shutdown:
        return "normal", fsd_reason or "shutdown"
    return "unclean", "no_clean_shutdown"


def evaluate_shutdown_readiness(
    *,
    ups_present: bool,
    guest_shutdown_budget_seconds: int | None,
    previous_shutdown: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if not ups_present:
        return {
            "status": "skip",
            "issues": [],
            "guest_shutdown_budget_seconds": guest_shutdown_budget_seconds,
            "history_available": previous_shutdown is not None,
        }

    issues: list[str] = []
    if guest_shutdown_budget_seconds is None:
        issues.append("shutdown_budget_unavailable")

    guests = previous_shutdown.get("guests") if isinstance(previous_shutdown, Mapping) else None
    if isinstance(guests, Mapping):
        for kind in ("vm", "lxc"):
            records = guests.get(kind)
            if not isinstance(records, Mapping):
                continue
            for guest_id, raw in sorted(records.items(), key=lambda item: str(item[0])):
                if not isinstance(raw, Mapping):
                    continue
                result = str(raw.get("result") or "unknown")
                forced = bool(raw.get("forced"))
                ratio = raw.get("timeout_ratio")
                if forced or result in {"timeout", "forced"}:
                    issues.append(f"{kind}:{guest_id}:{result}")
                elif isinstance(ratio, (int, float)) and not isinstance(ratio, bool) and ratio >= 0.8:
                    issues.append(f"{kind}:{guest_id}:near_timeout")

    return {
        "status": "warning" if issues else "ok",
        "issues": issues,
        "guest_shutdown_budget_seconds": guest_shutdown_budget_seconds,
        "history_available": previous_shutdown is not None,
    }


def _default_boot_id_reader() -> str:
    return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()


def _default_boot_time_reader() -> str:
    text = Path("/proc/stat").read_text(encoding="utf-8")
    match = re.search(r"(?m)^btime\s+(\d+)$", text)
    if match is None:
        return datetime.now(timezone.utc).astimezone().isoformat()
    return datetime.fromtimestamp(int(match.group(1)), timezone.utc).astimezone().isoformat()


def _default_previous_boot_journal_reader() -> str:
    completed = subprocess.run(
        ["journalctl", "-b", "-1", "-o", "short-iso-precise", "--no-pager"],
        capture_output=True,
        text=True,
        timeout=20.0,
        check=False,
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout or ""


def _duration_between(start: object, end: object) -> int | None:
    if not isinstance(start, str) or not isinstance(end, str):
        return None
    try:
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
    except ValueError:
        return None
    if start_dt.tzinfo is None or end_dt.tzinfo is None:
        return None
    return max(0, int(round((end_dt - start_dt).total_seconds())))


class ShutdownHistoryTracker:
    def __init__(
        self,
        *,
        state_store: StateStore,
        boot_id_reader: Callable[[], str] = _default_boot_id_reader,
        boot_time_reader: Callable[[], str] = _default_boot_time_reader,
        previous_boot_journal_reader: Callable[[], str] = _default_previous_boot_journal_reader,
        now_iso: Callable[[], str] | None = None,
    ) -> None:
        self.state_store = state_store
        self.boot_id_reader = boot_id_reader
        self.boot_time_reader = boot_time_reader
        self.previous_boot_journal_reader = previous_boot_journal_reader
        self.now_iso = now_iso or (lambda: datetime.now().astimezone().isoformat())

    def _load(self) -> dict[str, Any]:
        state = self.state_store.load()
        history = state.get("history")
        if not isinstance(history, list):
            state["history"] = []
        return state

    def startup(self) -> dict[str, Any]:
        state = self._load()
        boot_id = self.boot_id_reader().strip()
        boot_at = self.boot_time_reader()
        current = state.get("current_boot")

        if not isinstance(current, Mapping):
            state["current_boot"] = {"boot_id": boot_id, "boot_at": boot_at}
            state.setdefault("previous_shutdown", None)
            self.state_store.save(state)
            return self.payload()

        if str(current.get("boot_id") or "") == boot_id:
            return self.payload()

        journal = self.previous_boot_journal_reader()
        parsed = parse_guest_shutdown_journal(journal)
        shutdown_class, shutdown_reason = classify_previous_shutdown(
            clean_shutdown=bool(parsed["clean_shutdown"]),
            fsd_reason=(
                str(current.get("fsd_reason"))
                if isinstance(current.get("fsd_reason"), str)
                else None
            ),
        )

        previous = {
            "boot_id": current.get("boot_id"),
            "boot_at": current.get("boot_at"),
            "shutdown_at": parsed.get("shutdown_at"),
            "shutdown_class": shutdown_class,
            "shutdown_reason": shutdown_reason,
            "uptime_seconds": _duration_between(current.get("boot_at"), parsed.get("shutdown_at")),
            "downtime_seconds": _duration_between(parsed.get("shutdown_at"), boot_at),
            "outage_started_at": current.get("outage_started_at"),
            "fsd_at": current.get("fsd_at"),
            "ups_status_at_fsd": current.get("ups_status_at_fsd"),
            "battery_charge_at_fsd": current.get("battery_charge_at_fsd"),
            "battery_runtime_at_fsd": current.get("battery_runtime_at_fsd"),
            "ups_load_at_fsd": current.get("ups_load_at_fsd"),
            "all_guests_stopped_at": parsed.get("all_guests_stopped_at"),
            "guest_shutdown_total_seconds": parsed.get("guest_shutdown_total_seconds"),
            "guests": parsed.get("guests"),
        }

        history = [item for item in state.get("history", []) if isinstance(item, Mapping)]
        history.append(previous)
        state["history"] = history[-HISTORY_LIMIT:]
        state["previous_shutdown"] = previous
        state["current_boot"] = {"boot_id": boot_id, "boot_at": boot_at}
        self.state_store.save(state)
        return self.payload()

    def observe_ups(self, snapshot: UpsSnapshot) -> None:
        state = self._load()
        current = state.get("current_boot")
        if not isinstance(current, Mapping):
            self.startup()
            state = self._load()
            current = state.get("current_boot")
        if not isinstance(current, Mapping):
            return

        updated = dict(current)
        changed = False
        observed_at = self.now_iso()
        tokens = set(snapshot.status_tokens)

        if snapshot.on_battery and not isinstance(updated.get("outage_started_at"), str):
            updated["outage_started_at"] = observed_at
            changed = True

        if snapshot.line_power and "FSD" not in tokens and not isinstance(updated.get("fsd_at"), str):
            if "outage_started_at" in updated:
                updated.pop("outage_started_at", None)
                changed = True

        if "FSD" in tokens and not isinstance(updated.get("fsd_at"), str):
            if snapshot.low_battery:
                reason = "low_battery_fsd"
            elif snapshot.on_battery or isinstance(updated.get("outage_started_at"), str):
                reason = "on_battery_fsd"
            else:
                reason = "manual_or_external_fsd"
            updated.update(
                {
                    "fsd_at": observed_at,
                    "fsd_reason": reason,
                    "ups_status_at_fsd": snapshot.status_raw,
                    "battery_charge_at_fsd": snapshot.battery_charge_percent,
                    "battery_runtime_at_fsd": snapshot.runtime_seconds,
                    "ups_load_at_fsd": snapshot.load_percent,
                }
            )
            changed = True

        if changed:
            state["current_boot"] = updated
            self.state_store.save(state)

    def payload(self) -> dict[str, Any]:
        state = self._load()
        history = [dict(item) for item in state.get("history", []) if isinstance(item, Mapping)]
        current = state.get("current_boot")
        previous = state.get("previous_shutdown")
        return {
            "current_boot": dict(current) if isinstance(current, Mapping) else None,
            "previous_shutdown": dict(previous) if isinstance(previous, Mapping) else None,
            "history": history[-PUBLISHED_HISTORY_LIMIT:],
            "history_count": len(history),
        }
