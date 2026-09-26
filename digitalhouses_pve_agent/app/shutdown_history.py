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
HISTORY_PARSER_VERSION = 5
GUEST_SHUTDOWN_WARNING_RATIO = 0.8
GUEST_SHUTDOWN_CRITICAL_RATIO = 1.0

_TIMESTAMP_RE = re.compile(r"^(?P<ts>\S+)")
_START_RE = re.compile(
    r"\bStopping\s+(?P<kind>VM|CT)\s+(?P<id>\d+)\s+"
    r"\(timeout\s*=\s*(?P<timeout>\d+)\s+seconds\)",
    re.IGNORECASE,
)
_TASK_START_RE = re.compile(
    r"\bstarting task UPID:.*?:(?P<type>qmshutdown|vzshutdown):(?P<id>\d+):",
    re.IGNORECASE,
)
# A guest-agent liveness probe such as `guest-ping ... got timeout` is not
# evidence that the VM shutdown operation itself timed out. Only the explicit
# guest-shutdown QMP operation is treated as a shutdown timeout here. Generic
# Proxmox powerdown timeout markers are handled separately below.
_SHUTDOWN_TIMEOUT_RE = re.compile(
    r"\bVM\s+(?P<id>\d+)\b.*?\bqmp\b.*?\bguest-shutdown\b.*?"
    r"(?:got timeout|timed out)",
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
_FORCE_STOP_MARKERS = (
    "vm quit/powerdown failed - terminating now with sigterm",
    "vm still running - terminating now with sigkill",
)
_GENERIC_TIMEOUT_MARKER = "vm quit/powerdown failed - got timeout"
_SHUTDOWN_START_MARKERS = (
    "the system will power off now",
    "system is powering down",
)
_CLEAN_MARKERS = (
    "reached target shutdown.target",
    "reached target system power off",
    "systemd-shutdown",
)
_FSD_REASONS = {
    "on_battery_fsd",
    "low_battery_fsd",
    "charge_guard",
    "runtime_guard",
}


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
    if start is None or end is None or end < start:
        return None
    return int(round((end - start).total_seconds()))


def _guest_kind(token: str) -> str:
    return "vm" if token.casefold() == "vm" else "lxc"


def _empty_guest(kind: str, guest_id: str, timeout: int | None = None) -> dict[str, Any]:
    return {
        "kind": kind,
        "guest_id": guest_id,
        "timeout_seconds": timeout,
        "started_at": None,
        "finished_at": None,
        "duration_seconds": None,
        "timeout_ratio": None,
        "assessment": "unknown",
        "result": "unknown",
        "forced": False,
    }


def _guest_shutdown_assessment(
    *,
    result: object,
    forced: object,
    timeout_ratio: object,
) -> str:
    normalized_result = str(result or "unknown").casefold()
    if bool(forced) or normalized_result in {"timeout", "forced"}:
        return "critical"
    if normalized_result != "clean":
        return "unknown"
    if not isinstance(timeout_ratio, (int, float)) or isinstance(timeout_ratio, bool):
        return "unknown"
    if timeout_ratio >= GUEST_SHUTDOWN_CRITICAL_RATIO:
        return "critical"
    if timeout_ratio >= GUEST_SHUTDOWN_WARNING_RATIO:
        return "warning"
    if timeout_ratio >= 0:
        return "ok"
    return "unknown"


def _normalized_guest_fact(
    raw: Mapping[str, Any],
    *,
    kind: str,
    guest_id: str,
    name: str | None = None,
) -> dict[str, Any]:
    item = dict(raw)
    item["kind"] = kind
    item["guest_id"] = guest_id

    stored_name = item.get("name")
    if not isinstance(stored_name, str) or not stored_name.strip():
        if isinstance(name, str) and name.strip():
            item["name"] = name.strip()

    duration = item.get("duration_seconds")
    timeout = item.get("timeout_seconds")
    ratio = item.get("timeout_ratio")
    if (
        (not isinstance(ratio, (int, float)) or isinstance(ratio, bool))
        and isinstance(duration, int)
        and not isinstance(duration, bool)
        and isinstance(timeout, int)
        and not isinstance(timeout, bool)
        and timeout > 0
    ):
        ratio = round(duration / timeout, 3)
        item["timeout_ratio"] = ratio

    item["assessment"] = _guest_shutdown_assessment(
        result=item.get("result"),
        forced=item.get("forced"),
        timeout_ratio=ratio,
    )
    return item


def _normalize_history_guests(guests: object) -> dict[str, dict[str, dict[str, Any]]]:
    normalized: dict[str, dict[str, dict[str, Any]]] = {"vm": {}, "lxc": {}}
    if not isinstance(guests, Mapping):
        return normalized

    for kind in ("vm", "lxc"):
        records = guests.get(kind)
        if not isinstance(records, Mapping):
            continue
        for guest_id_raw, raw in records.items():
            if not isinstance(raw, Mapping):
                continue
            guest_id = str(guest_id_raw)
            normalized[kind][guest_id] = _normalized_guest_fact(
                raw,
                kind=kind,
                guest_id=guest_id,
            )
    return normalized


def _begin_guest_shutdown(
    records: dict[tuple[str, str], dict[str, Any]],
    active_guests: set[tuple[str, str]],
    *,
    kind: str,
    guest_id: str,
    timestamp: datetime | None,
    timeout: int | None,
    first_started: datetime | None,
) -> datetime | None:
    key = (kind, guest_id)
    was_active = key in active_guests
    item = records.setdefault(key, _empty_guest(kind, guest_id, timeout))

    if timeout is not None:
        item["timeout_seconds"] = timeout

    if not was_active:
        if timeout is None:
            # A new standalone qm/pct task has no timeout in the task line.
            # Do not leak timeout metadata from an older shutdown of this guest.
            item["timeout_seconds"] = None
        item.update(
            {
                "finished_at": None,
                "duration_seconds": None,
                "timeout_ratio": None,
                "assessment": "unknown",
                "result": "unknown",
                "forced": False,
            }
        )
        if timestamp is not None:
            item["started_at"] = timestamp.isoformat()
            if first_started is None or timestamp < first_started:
                first_started = timestamp

    active_guests.add(key)
    return first_started


def parse_guest_shutdown_journal(text: str) -> dict[str, Any]:
    records: dict[tuple[str, str], dict[str, Any]] = {}
    active_guests: set[tuple[str, str]] = set()
    first_started: datetime | None = None
    last_timestamp: datetime | None = None
    clean_shutdown_at: datetime | None = None
    all_stopped_at: datetime | None = None
    clean_shutdown = False
    journal_has_evidence = False
    shutdown_scope_started = False

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        journal_has_evidence = True
        timestamp = _parse_timestamp(line)
        if timestamp is not None:
            last_timestamp = timestamp

        lowered = line.casefold()
        if (
            not shutdown_scope_started
            and any(marker in lowered for marker in _SHUTDOWN_START_MARKERS)
        ):
            # The previous-boot journal covers the entire boot and may contain
            # unrelated manual guest shutdowns. Once host shutdown begins,
            # only guest operations from this final shutdown sequence are
            # relevant to shutdown-history evidence.
            shutdown_scope_started = True
            records.clear()
            active_guests.clear()
            first_started = None
            all_stopped_at = None
            clean_shutdown = False
            clean_shutdown_at = None

        if any(marker in lowered for marker in _CLEAN_MARKERS):
            clean_shutdown = True
            if timestamp is not None:
                clean_shutdown_at = timestamp

        task_start = _TASK_START_RE.search(line)
        if task_start is not None:
            kind = (
                "vm"
                if task_start.group("type").casefold() == "qmshutdown"
                else "lxc"
            )
            first_started = _begin_guest_shutdown(
                records,
                active_guests,
                kind=kind,
                guest_id=task_start.group("id"),
                timestamp=timestamp,
                timeout=None,
                first_started=first_started,
            )
            continue

        start = _START_RE.search(line)
        if start is not None:
            first_started = _begin_guest_shutdown(
                records,
                active_guests,
                kind=_guest_kind(start.group("kind")),
                guest_id=start.group("id"),
                timestamp=timestamp,
                timeout=int(start.group("timeout")),
                first_started=first_started,
            )
            continue

        shutdown_timeout = _SHUTDOWN_TIMEOUT_RE.search(line)
        if shutdown_timeout is not None:
            guest_id = shutdown_timeout.group("id")
            key = ("vm", guest_id)
            item = records.setdefault(key, _empty_guest("vm", guest_id))
            item["result"] = "timeout"
            continue

        end_match = _END_TASK_RE.search(line)
        if end_match is not None:
            kind = "vm" if end_match.group("type").casefold() == "qmshutdown" else "lxc"
            guest_id = end_match.group("id")
            key = (kind, guest_id)
            item = records.setdefault(key, _empty_guest(kind, guest_id))
            if timestamp is not None:
                item["finished_at"] = timestamp.isoformat()
            tail = line[end_match.end() :].casefold()
            if "got timeout" in tail or "timed out" in tail:
                item["result"] = "timeout"
            elif any(marker in tail for marker in _FORCE_STOP_MARKERS):
                item["result"] = "forced"
                item["forced"] = True
            elif item["result"] == "unknown":
                item["result"] = "clean"
            active_guests.discard(key)
            continue

        if len(active_guests) == 1:
            active_key = next(iter(active_guests))
            active_item = records.get(active_key)
            if active_item is not None:
                if any(marker in lowered for marker in _FORCE_STOP_MARKERS):
                    active_item["result"] = "forced"
                    active_item["forced"] = True
                    continue
                if _GENERIC_TIMEOUT_MARKER in lowered:
                    active_item["result"] = "timeout"
                    continue

        simple_end = _SIMPLE_END_RE.search(line)
        if simple_end is not None:
            kind = _guest_kind(simple_end.group("kind"))
            guest_id = simple_end.group("id")
            key = (kind, guest_id)
            item = records.setdefault(key, _empty_guest(kind, guest_id))
            if timestamp is not None:
                item["finished_at"] = timestamp.isoformat()
            if item["result"] == "unknown":
                item["result"] = "clean"
            active_guests.discard(key)
            continue

        if _ALL_STOPPED_RE.search(line) and timestamp is not None:
            all_stopped_at = timestamp
            active_guests.clear()

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
        if started is not None and finished is not None and finished < started:
            finished = None
            item["finished_at"] = None
            if item.get("result") == "clean":
                item["result"] = "unknown"
        duration = _seconds(started, finished)
        item["duration_seconds"] = duration
        timeout = item.get("timeout_seconds")
        if duration is not None and isinstance(timeout, int) and timeout > 0:
            item["timeout_ratio"] = round(duration / timeout, 3)
        item["assessment"] = _guest_shutdown_assessment(
            result=item.get("result"),
            forced=item.get("forced"),
            timeout_ratio=item.get("timeout_ratio"),
        )
        if finished is not None and (latest_finished is None or finished > latest_finished):
            latest_finished = finished
        guests[kind][guest_id] = item

    stop_boundary = all_stopped_at or (
        latest_finished if not active_guests else None
    )
    total = _seconds(first_started, stop_boundary)
    clean_result: bool | None = clean_shutdown if journal_has_evidence else None
    return {
        "guests": guests,
        "all_guests_stopped_at": _iso(all_stopped_at),
        "guest_shutdown_total_seconds": total,
        "clean_shutdown": clean_result,
        "shutdown_at": _iso(clean_shutdown_at),
        "last_journal_at": _iso(last_timestamp),
    }


def classify_previous_shutdown(
    *,
    clean_shutdown: bool | None,
    fsd_reason: str | None,
) -> tuple[str, str]:
    if fsd_reason in _FSD_REASONS:
        return "ups_power", fsd_reason
    if clean_shutdown is True:
        return "normal", fsd_reason or "shutdown"
    if clean_shutdown is False:
        return "unclean", fsd_reason or "unknown"
    return "unknown", fsd_reason or "unknown"


def evaluate_shutdown_readiness(
    *,
    ups_present: bool,
    guest_shutdown_budget_seconds: int | None,
    previous_shutdown: Mapping[str, Any] | None,
    guest_shutdowns: Mapping[str, Any] | None = None,
    additional_issues: list[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    if not ups_present:
        return {
            "status": "skip",
            "issues": [],
            "guest_shutdown_budget_seconds": guest_shutdown_budget_seconds,
            "history_available": previous_shutdown is not None,
        }

    issues = [str(issue) for issue in additional_issues if str(issue)]
    if guest_shutdown_budget_seconds is None:
        issues.append("shutdown_budget_unavailable")

    if isinstance(previous_shutdown, Mapping) and previous_shutdown.get("shutdown_class") == "ups_power":
        shutdown_clean = previous_shutdown.get("shutdown_clean")
        if shutdown_clean is False:
            issues.append("previous_host_shutdown_unclean")
        elif shutdown_clean is not True:
            issues.append("previous_host_shutdown_unknown")

    guests: object = guest_shutdowns
    if not isinstance(guests, Mapping):
        guests = (
            previous_shutdown.get("guests")
            if isinstance(previous_shutdown, Mapping)
            else None
        )
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
                ratio = raw.get("current_timeout_ratio")
                if not isinstance(ratio, (int, float)) or isinstance(ratio, bool):
                    ratio = raw.get("timeout_ratio")
                if forced or result in {"timeout", "forced"}:
                    issues.append(f"{kind}:{guest_id}:{result}")
                elif (
                    isinstance(ratio, (int, float))
                    and not isinstance(ratio, bool)
                    and ratio >= GUEST_SHUTDOWN_WARNING_RATIO
                ):
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


def _default_current_boot_journal_reader() -> str:
    completed = subprocess.run(
        ["journalctl", "-b", "0", "-o", "short-iso-precise", "--no-pager"],
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


def _parsed_guest_history(
    parsed: object,
    guest_names: object = None,
) -> dict[str, dict[str, dict[str, Any]]]:
    guests: dict[str, dict[str, dict[str, Any]]] = {"vm": {}, "lxc": {}}
    if not isinstance(parsed, Mapping):
        return guests

    names = guest_names if isinstance(guest_names, Mapping) else {}
    for kind in ("vm", "lxc"):
        records = parsed.get(kind)
        if not isinstance(records, Mapping):
            continue
        kind_names = names.get(kind)
        if not isinstance(kind_names, Mapping):
            kind_names = {}
        for guest_id_raw, raw in records.items():
            if not isinstance(raw, Mapping):
                continue
            guest_id = str(guest_id_raw)
            name_raw = kind_names.get(guest_id)
            name = name_raw if isinstance(name_raw, str) else None
            guests[kind][guest_id] = _normalized_guest_fact(
                raw,
                kind=kind,
                guest_id=guest_id,
                name=name,
            )
    return guests


def _shutdown_status(clean: bool | None) -> str:
    if clean is True:
        return "correct"
    if clean is False:
        return "incorrect"
    return "unknown"


def _guest_record_time(raw: Mapping[str, Any]) -> datetime | None:
    value = raw.get("finished_at")
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _merge_guest_last_shutdowns(
    state: dict[str, Any],
    guests: object,
    *,
    source: str,
) -> bool:
    if not isinstance(guests, Mapping):
        return False

    existing_raw = state.get("guest_last_shutdowns")
    existing: dict[str, dict[str, dict[str, Any]]] = {"vm": {}, "lxc": {}}
    if isinstance(existing_raw, Mapping):
        for kind in ("vm", "lxc"):
            records = existing_raw.get(kind)
            if isinstance(records, Mapping):
                existing[kind] = {
                    str(guest_id): dict(raw)
                    for guest_id, raw in records.items()
                    if isinstance(raw, Mapping)
                }

    changed = False
    for kind in ("vm", "lxc"):
        records = guests.get(kind)
        if not isinstance(records, Mapping):
            continue
        for guest_id, raw in records.items():
            if not isinstance(raw, Mapping):
                continue
            duration = raw.get("duration_seconds")
            finished_at = raw.get("finished_at")
            if not isinstance(duration, int) or isinstance(duration, bool):
                continue
            if not isinstance(finished_at, str):
                continue

            candidate = dict(raw)
            candidate["source"] = source
            key = str(guest_id)
            previous = existing[kind].get(key)
            previous_time = _guest_record_time(previous) if isinstance(previous, Mapping) else None
            candidate_time = _guest_record_time(candidate)
            if candidate_time is None:
                continue
            if (
                previous_time is None
                or candidate_time > previous_time
                or (
                    candidate_time == previous_time
                    and source == "pve_shutdown"
                    and previous is not None
                    and previous.get("source") != "pve_shutdown"
                )
            ):
                existing[kind][key] = candidate
                changed = True

    if changed or not isinstance(existing_raw, Mapping):
        state["guest_last_shutdowns"] = existing
    return changed


def _previous_from_parsed(
    *,
    source: Mapping[str, Any],
    parsed: Mapping[str, Any],
    next_boot_at: object,
) -> dict[str, Any]:
    raw_shutdown_clean = parsed.get("clean_shutdown")
    shutdown_clean = (
        raw_shutdown_clean if isinstance(raw_shutdown_clean, bool) else None
    )

    raw_reason = source.get("fsd_reason")
    if not isinstance(raw_reason, str):
        existing_reason = source.get("shutdown_reason")
        raw_reason = existing_reason if isinstance(existing_reason, str) and existing_reason in _FSD_REASONS else None

    shutdown_class, shutdown_reason = classify_previous_shutdown(
        clean_shutdown=shutdown_clean,
        fsd_reason=raw_reason,
    )

    shutdown_at = parsed.get("shutdown_at")
    if not isinstance(shutdown_at, str):
        shutdown_at = None
    all_guests_stopped_at = parsed.get("all_guests_stopped_at")
    if not isinstance(all_guests_stopped_at, str):
        all_guests_stopped_at = None
    outage_started_at = source.get("outage_started_at")
    fsd_at = source.get("fsd_at")
    parsed_total = parsed.get("guest_shutdown_total_seconds")
    guest_total_seconds = parsed_total if isinstance(parsed_total, int) else None
    fsd_to_shutdown_seconds = _duration_between(fsd_at, shutdown_at)
    all_guests_stopped_to_shutdown_seconds = _duration_between(
        all_guests_stopped_at,
        shutdown_at,
    )
    actual_shutdown_seconds: int | None = None
    if fsd_to_shutdown_seconds is not None:
        actual_shutdown_seconds = fsd_to_shutdown_seconds
    elif (
        guest_total_seconds is not None
        and all_guests_stopped_to_shutdown_seconds is not None
    ):
        actual_shutdown_seconds = (
            guest_total_seconds + all_guests_stopped_to_shutdown_seconds
        )

    return {
        "history_parser_version": HISTORY_PARSER_VERSION,
        "boot_id": source.get("boot_id"),
        "boot_at": source.get("boot_at"),
        "shutdown_at": shutdown_at,
        "last_journal_at": parsed.get("last_journal_at"),
        "shutdown_class": shutdown_class,
        "shutdown_reason": shutdown_reason,
        "shutdown_clean": shutdown_clean,
        "shutdown_status": _shutdown_status(shutdown_clean),
        "shutdown_budget_fingerprint": source.get("shutdown_budget_fingerprint"),
        "planned_shutdown_seconds": source.get("planned_shutdown_seconds"),
        "planned_guest_shutdown_seconds": source.get("planned_guest_shutdown_seconds"),
        "planned_all_guest_shutdown_seconds": source.get(
            "planned_all_guest_shutdown_seconds"
        ),
        "running_guests": source.get("running_guests", []),
        "shutdown_sequence": source.get("shutdown_sequence", []),
        "actual_shutdown_seconds": actual_shutdown_seconds,
        "uptime_seconds": _duration_between(source.get("boot_at"), shutdown_at),
        "downtime_seconds": _duration_between(shutdown_at, next_boot_at),
        "outage_started_at": outage_started_at,
        "fsd_at": fsd_at,
        "ups_status_at_fsd": source.get("ups_status_at_fsd"),
        "battery_charge_at_fsd": source.get("battery_charge_at_fsd"),
        "battery_runtime_at_fsd": source.get("battery_runtime_at_fsd"),
        "ups_load_at_fsd": source.get("ups_load_at_fsd"),
        "all_guests_stopped_at": all_guests_stopped_at,
        "guest_shutdown_total_seconds": guest_total_seconds,
        "actual_guest_shutdown_seconds": guest_total_seconds,
        "outage_to_fsd_seconds": _duration_between(outage_started_at, fsd_at),
        "fsd_to_all_guests_stopped_seconds": _duration_between(fsd_at, all_guests_stopped_at),
        "fsd_to_shutdown_seconds": fsd_to_shutdown_seconds,
        "all_guests_stopped_to_shutdown_seconds": all_guests_stopped_to_shutdown_seconds,
        "outage_to_shutdown_seconds": _duration_between(outage_started_at, shutdown_at),
        "guests": _parsed_guest_history(
            parsed.get("guests"),
            source.get("guest_names"),
        ),
    }


class ShutdownHistoryTracker:
    def __init__(
        self,
        *,
        state_store: StateStore,
        boot_id_reader: Callable[[], str] = _default_boot_id_reader,
        boot_time_reader: Callable[[], str] = _default_boot_time_reader,
        previous_boot_journal_reader: Callable[[], str] = _default_previous_boot_journal_reader,
        current_boot_journal_reader: Callable[[], str] = _default_current_boot_journal_reader,
        now_iso: Callable[[], str] | None = None,
    ) -> None:
        self.state_store = state_store
        self.boot_id_reader = boot_id_reader
        self.boot_time_reader = boot_time_reader
        self.previous_boot_journal_reader = previous_boot_journal_reader
        self.current_boot_journal_reader = current_boot_journal_reader
        self.now_iso = now_iso or (lambda: datetime.now().astimezone().isoformat())

    def _load(self) -> dict[str, Any]:
        state = self.state_store.load()
        history = state.get("history")
        if not isinstance(history, list):
            state["history"] = []
        else:
            normalized_history: list[dict[str, Any]] = []
            for raw in history:
                if not isinstance(raw, Mapping):
                    continue
                item = dict(raw)
                clean = item.get("shutdown_clean")
                item["shutdown_status"] = _shutdown_status(
                    clean if isinstance(clean, bool) else None
                )
                item["guests"] = _normalize_history_guests(item.get("guests"))
                normalized_history.append(item)
            state["history"] = normalized_history

        previous = state.get("previous_shutdown")
        if isinstance(previous, Mapping):
            normalized_previous = dict(previous)
            clean = normalized_previous.get("shutdown_clean")
            normalized_previous["shutdown_status"] = _shutdown_status(
                clean if isinstance(clean, bool) else None
            )
            normalized_previous["guests"] = _normalize_history_guests(
                normalized_previous.get("guests")
            )
            state["previous_shutdown"] = normalized_previous

        latest = state.get("guest_last_shutdowns")
        if not isinstance(latest, Mapping):
            state["guest_last_shutdowns"] = {"vm": {}, "lxc": {}}
        else:
            state["guest_last_shutdowns"] = {
                "vm": {
                    str(guest_id): _normalized_guest_fact(
                        raw,
                        kind="vm",
                        guest_id=str(guest_id),
                    )
                    for guest_id, raw in latest.get("vm", {}).items()
                    if isinstance(raw, Mapping)
                }
                if isinstance(latest.get("vm"), Mapping)
                else {},
                "lxc": {
                    str(guest_id): _normalized_guest_fact(
                        raw,
                        kind="lxc",
                        guest_id=str(guest_id),
                    )
                    for guest_id, raw in latest.get("lxc", {}).items()
                    if isinstance(raw, Mapping)
                }
                if isinstance(latest.get("lxc"), Mapping)
                else {},
            }
        return state

    def _reconcile_previous_parser(self, state: dict[str, Any], *, current_boot_at: object) -> bool:
        previous = state.get("previous_shutdown")
        if not isinstance(previous, Mapping):
            return False
        version = previous.get("history_parser_version")
        if isinstance(version, int) and version >= HISTORY_PARSER_VERSION:
            return False

        journal = self.previous_boot_journal_reader()
        if not journal.strip():
            return False
        parsed = parse_guest_shutdown_journal(journal)
        if parsed.get("last_journal_at") is None:
            return False

        reconciled = _previous_from_parsed(
            source=previous,
            parsed=parsed,
            next_boot_at=current_boot_at,
        )
        state["previous_shutdown"] = reconciled
        _merge_guest_last_shutdowns(
            state,
            reconciled.get("guests"),
            source="pve_shutdown",
        )

        previous_boot_id = reconciled.get("boot_id")
        history: list[dict[str, Any]] = []
        replaced = False
        for raw in state.get("history", []):
            if not isinstance(raw, Mapping):
                continue
            item = dict(raw)
            if previous_boot_id is not None and item.get("boot_id") == previous_boot_id:
                history.append(dict(reconciled))
                replaced = True
            else:
                history.append(item)
        if not replaced:
            history.append(dict(reconciled))
        state["history"] = history[-HISTORY_LIMIT:]
        return True

    def startup(self) -> dict[str, Any]:
        raw_state = self.state_store.load()
        state = self._load()
        normalized_changed = state != raw_state
        boot_id = self.boot_id_reader().strip()
        boot_at = self.boot_time_reader()
        current = state.get("current_boot")

        if not isinstance(current, Mapping):
            state["current_boot"] = {"boot_id": boot_id, "boot_at": boot_at}
            state.setdefault("previous_shutdown", None)
            self.state_store.save(state)
            return self.payload()

        if str(current.get("boot_id") or "") == boot_id:
            reconciled = self._reconcile_previous_parser(
                state,
                current_boot_at=current.get("boot_at") or boot_at,
            )
            if normalized_changed or reconciled:
                self.state_store.save(state)
            return self.payload()

        journal = self.previous_boot_journal_reader()
        parsed = parse_guest_shutdown_journal(journal)
        previous = _previous_from_parsed(
            source=current,
            parsed=parsed,
            next_boot_at=boot_at,
        )

        history = [item for item in state.get("history", []) if isinstance(item, Mapping)]
        history.append(previous)
        state["history"] = history[-HISTORY_LIMIT:]
        state["previous_shutdown"] = previous
        _merge_guest_last_shutdowns(
            state,
            previous.get("guests"),
            source="pve_shutdown",
        )
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

    def record_guest_inventory(
        self,
        guest_names: Mapping[tuple[str, str], str],
    ) -> None:
        normalized: dict[str, dict[str, str]] = {"vm": {}, "lxc": {}}
        for key, name_raw in guest_names.items():
            if (
                not isinstance(key, tuple)
                or len(key) != 2
                or key[0] not in {"vm", "lxc"}
                or not str(key[1])
                or not isinstance(name_raw, str)
                or not name_raw.strip()
            ):
                continue
            kind, guest_id_raw = key
            normalized[kind][str(guest_id_raw)] = name_raw.strip()

        state = self._load()
        current = state.get("current_boot")
        if not isinstance(current, Mapping):
            self.startup()
            state = self._load()
            current = state.get("current_boot")
        if not isinstance(current, Mapping):
            return

        updated = dict(current)
        if updated.get("guest_names") == normalized:
            return
        updated["guest_names"] = normalized
        state["current_boot"] = updated
        self.state_store.save(state)

    def record_shutdown_budget_fingerprint(self, fingerprint: str) -> None:
        if not isinstance(fingerprint, str) or not fingerprint.strip():
            raise ValueError("shutdown budget fingerprint must be a non-empty string")
        normalized = fingerprint.strip()
        state = self._load()
        current = state.get("current_boot")
        if not isinstance(current, Mapping):
            self.startup()
            state = self._load()
            current = state.get("current_boot")
        if not isinstance(current, Mapping):
            return
        if current.get("shutdown_budget_fingerprint") == normalized:
            return
        updated = dict(current)
        updated["shutdown_budget_fingerprint"] = normalized
        state["current_boot"] = updated
        self.state_store.save(state)

    def record_shutdown_plan(
        self,
        *,
        configuration_fingerprint: str,
        planned_shutdown_seconds: int | None,
        planned_guest_shutdown_seconds: int | None,
        planned_all_guest_shutdown_seconds: int | None,
        running_guests: list[str] | tuple[str, ...],
        shutdown_sequence: list[list[str]] | tuple[tuple[str, ...], ...],
    ) -> None:
        if not isinstance(configuration_fingerprint, str) or not configuration_fingerprint.strip():
            raise ValueError("shutdown plan fingerprint must be a non-empty string")

        def seconds(value: object) -> int | None:
            if value is None:
                return None
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError("shutdown plan seconds must be non-negative integers")
            return value

        normalized_guests = [str(value) for value in running_guests]
        normalized_sequence = [
            [str(value) for value in group]
            for group in shutdown_sequence
        ]

        state = self._load()
        current = state.get("current_boot")
        if not isinstance(current, Mapping):
            self.startup()
            state = self._load()
            current = state.get("current_boot")
        if not isinstance(current, Mapping):
            return

        updated = dict(current)
        updated.update(
            {
                "shutdown_budget_fingerprint": configuration_fingerprint.strip(),
                "planned_shutdown_seconds": seconds(planned_shutdown_seconds),
                "planned_guest_shutdown_seconds": seconds(
                    planned_guest_shutdown_seconds
                ),
                "planned_all_guest_shutdown_seconds": seconds(
                    planned_all_guest_shutdown_seconds
                ),
                "running_guests": normalized_guests,
                "shutdown_sequence": normalized_sequence,
            }
        )
        if updated == dict(current):
            return
        state["current_boot"] = updated
        self.state_store.save(state)

    def refresh_current_guest_shutdowns(self) -> bool:
        journal = self.current_boot_journal_reader()
        if not journal.strip():
            return False
        parsed = parse_guest_shutdown_journal(journal)
        state = self._load()
        changed = _merge_guest_last_shutdowns(
            state,
            parsed.get("guests"),
            source="guest_shutdown",
        )
        if changed:
            self.state_store.save(state)
        return changed

    def enrich_guest_last_shutdowns(
        self,
        guest_timeouts: Mapping[tuple[str, str], int],
    ) -> bool:
        state = self._load()
        latest = state.get("guest_last_shutdowns")
        if not isinstance(latest, Mapping):
            return False

        changed = False
        for key, timeout_seconds in guest_timeouts.items():
            if (
                not isinstance(key, tuple)
                or len(key) != 2
                or key[0] not in {"vm", "lxc"}
                or not str(key[1])
                or not isinstance(timeout_seconds, int)
                or isinstance(timeout_seconds, bool)
                or timeout_seconds < 0
            ):
                continue

            kind, guest_id_raw = key
            guest_id = str(guest_id_raw)
            records = latest.get(kind)
            if not isinstance(records, dict):
                continue
            raw = records.get(guest_id)
            if not isinstance(raw, Mapping):
                continue

            item = dict(raw)
            stored_timeout = item.get("timeout_seconds")
            if stored_timeout is None:
                item["timeout_seconds"] = timeout_seconds
                stored_timeout = timeout_seconds

            duration = item.get("duration_seconds")
            ratio: float | None = None
            if (
                isinstance(duration, int)
                and not isinstance(duration, bool)
                and isinstance(stored_timeout, int)
                and not isinstance(stored_timeout, bool)
                and stored_timeout > 0
            ):
                ratio = round(duration / stored_timeout, 3)

            assessment = _guest_shutdown_assessment(
                result=item.get("result"),
                forced=item.get("forced"),
                timeout_ratio=ratio,
            )

            current_ratio: float | None = None
            if (
                isinstance(duration, int)
                and not isinstance(duration, bool)
                and timeout_seconds > 0
            ):
                current_ratio = round(duration / timeout_seconds, 3)
            current_assessment = _guest_shutdown_assessment(
                result=item.get("result"),
                forced=item.get("forced"),
                timeout_ratio=current_ratio,
            )

            if item.get("timeout_ratio") != ratio:
                item["timeout_ratio"] = ratio
            if item.get("assessment") != assessment:
                item["assessment"] = assessment
            if item.get("current_timeout_seconds") != timeout_seconds:
                item["current_timeout_seconds"] = timeout_seconds
            if item.get("current_timeout_ratio") != current_ratio:
                item["current_timeout_ratio"] = current_ratio
            if item.get("current_assessment") != current_assessment:
                item["current_assessment"] = current_assessment

            if item != dict(raw):
                records[guest_id] = item
                changed = True

        if changed:
            state["guest_last_shutdowns"] = latest
            self.state_store.save(state)
        return changed

    def record_software_shutdown_commit(self, reason: str, snapshot: UpsSnapshot) -> None:
        if reason not in {"charge_guard", "runtime_guard"}:
            raise ValueError("unsupported software shutdown reason")
        state = self._load()
        current = state.get("current_boot")
        if not isinstance(current, Mapping):
            self.startup()
            state = self._load()
            current = state.get("current_boot")
        if not isinstance(current, Mapping):
            return
        if isinstance(current.get("fsd_at"), str):
            return
        updated = dict(current)
        updated.update(
            {
                "fsd_at": self.now_iso(),
                "fsd_reason": reason,
                "ups_status_at_fsd": snapshot.status_raw,
                "battery_charge_at_fsd": snapshot.battery_charge_percent,
                "battery_runtime_at_fsd": snapshot.runtime_seconds,
                "ups_load_at_fsd": snapshot.load_percent,
            }
        )
        state["current_boot"] = updated
        self.state_store.save(state)

    def payload(self) -> dict[str, Any]:
        state = self._load()
        history = [dict(item) for item in state.get("history", []) if isinstance(item, Mapping)]
        current = state.get("current_boot")
        previous = state.get("previous_shutdown")
        latest = state.get("guest_last_shutdowns")
        return {
            "current_boot": dict(current) if isinstance(current, Mapping) else None,
            "previous_shutdown": dict(previous) if isinstance(previous, Mapping) else None,
            "guest_last_shutdowns": (
                {
                    "vm": dict(latest.get("vm", {})),
                    "lxc": dict(latest.get("lxc", {})),
                }
                if isinstance(latest, Mapping)
                else {"vm": {}, "lxc": {}}
            ),
            "history": history[-PUBLISHED_HISTORY_LIMIT:],
            "history_count": len(history),
        }
