"""Persistent current-month outage state."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


class ContractDataError(RuntimeError):
    """Raised when existing persisted runtime state violates its contract."""


def load_json_object(path: Path, *, label: str) -> dict[str, Any] | None:
    """Load one persisted JSON object.

    A genuinely missing file means fresh state. Existing unreadable, malformed,
    or non-object content is a contract failure and must not be replaced with
    healthy defaults.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ContractDataError(f"unable to read {label} state {path}: {exc}") from exc

    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ContractDataError(f"invalid JSON in {label} state {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ContractDataError(f"{label} state {path} must be a JSON object")
    return raw


def _parse_datetime(
    value: Any,
    *,
    field: str,
    timezone,
    allow_none: bool = True,
) -> datetime | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or not value:
        raise ContractDataError(f"{field} must be an ISO-8601 string or null")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ContractDataError(f"{field} must be valid ISO-8601") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone)
    return parsed


def _nonnegative_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractDataError(f"{field} must be a non-negative integer")
    return value


def now_local() -> datetime:
    return datetime.now().astimezone()


def month_key(value: datetime) -> str:
    return value.strftime("%Y-%m")


def iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def duration_text(total_seconds: int) -> str:
    total_seconds = max(0, int(total_seconds))
    hours, rem = divmod(total_seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def load_discovery_components(path: Path) -> set[str]:
    raw = load_json_object(path, label="discovery")
    if raw is None:
        return set()
    if raw.get("schema_version") != 1:
        raise ContractDataError("discovery.schema_version must be 1")
    components = raw.get("optional_components")
    if not isinstance(components, list):
        raise ContractDataError("discovery.optional_components must be a list")
    if any(not isinstance(item, str) or not item for item in components):
        raise ContractDataError(
            "discovery.optional_components must contain non-empty strings"
        )
    return set(components)


def save_discovery_components(path: Path, components: set[str]) -> None:
    atomic_write_json(
        path,
        {
            "schema_version": 1,
            "optional_components": sorted(components),
        },
    )


@dataclass
class RecoveryRuntimeState:
    stopped: bool = False
    cycle: int = 0
    cooldown_until: datetime | None = None

    @classmethod
    def load(cls, path: Path) -> "RecoveryRuntimeState":
        raw = load_json_object(path, label="recovery")
        if raw is None:
            return cls()
        if raw.get("schema_version") != 1:
            raise ContractDataError("recovery.schema_version must be 1")

        stopped = raw.get("stopped")
        if not isinstance(stopped, bool):
            raise ContractDataError("recovery.stopped must be boolean")

        cycle = _nonnegative_int(raw.get("cycle"), field="recovery.cycle")
        cooldown_until = _parse_datetime(
            raw.get("cooldown_until"),
            field="recovery.cooldown_until",
            timezone=now_local().tzinfo,
        )

        return cls(
            stopped=stopped,
            cycle=cycle,
            cooldown_until=cooldown_until,
        )

    def save(self, path: Path) -> None:
        atomic_write_json(
            path,
            {
                "schema_version": 1,
                "stopped": self.stopped,
                "cycle": self.cycle,
                "cooldown_until": (
                    iso(self.cooldown_until)
                    if self.cooldown_until is not None
                    else None
                ),
            },
        )

    def reset(self) -> None:
        self.stopped = False
        self.cycle = 0
        self.cooldown_until = None

    def cooldown_remaining(self, when: datetime | None = None) -> int:
        if self.cooldown_until is None:
            return 0
        when = when or now_local()
        seconds = (self.cooldown_until - when).total_seconds()
        return max(0, int(seconds + 0.999))


@dataclass
class OutageTracker:
    path: Path
    month: str
    outages: list[dict[str, Any]]
    active_from: datetime | None
    pending_from: datetime | None = None
    pending_attempts: int = 0

    @classmethod
    def load(cls, path: Path) -> "OutageTracker":
        now = now_local()
        current_month = month_key(now)
        raw = load_json_object(path, label="outages")
        if raw is None:
            return cls(path, current_month, [], None)

        month = raw.get("month")
        if not isinstance(month, str) or not month:
            raise ContractDataError("outages.month must be a non-empty string")

        outages = raw.get("outages")
        if not isinstance(outages, list):
            raise ContractDataError("outages.outages must be a list")
        for index, record in enumerate(outages):
            if not isinstance(record, dict):
                raise ContractDataError(
                    f"outages.outages[{index}] must be an object"
                )
            for field in ("from", "to", "duration"):
                if not isinstance(record.get(field), str) or not record[field]:
                    raise ContractDataError(
                        f"outages.outages[{index}].{field} must be a non-empty string"
                    )
            _parse_datetime(
                record["from"],
                field=f"outages.outages[{index}].from",
                timezone=now.tzinfo,
                allow_none=False,
            )
            _parse_datetime(
                record["to"],
                field=f"outages.outages[{index}].to",
                timezone=now.tzinfo,
                allow_none=False,
            )
            _nonnegative_int(
                record.get("duration_seconds"),
                field=f"outages.outages[{index}].duration_seconds",
            )

        active_from = _parse_datetime(
            raw.get("active_from"),
            field="outages.active_from",
            timezone=now.tzinfo,
        )
        pending_from = _parse_datetime(
            raw.get("pending_from"),
            field="outages.pending_from",
            timezone=now.tzinfo,
        )
        pending_attempts_raw = raw.get("pending_attempts", 0)
        pending_attempts = _nonnegative_int(
            pending_attempts_raw,
            field="outages.pending_attempts",
        )

        if pending_from is None and pending_attempts != 0:
            raise ContractDataError(
                "outages.pending_attempts must be 0 when pending_from is null"
            )
        if active_from is not None and (
            pending_from is not None or pending_attempts != 0
        ):
            raise ContractDataError(
                "outages cannot be active and pending at the same time"
            )

        if month != current_month:
            month_start = now.replace(
                day=1,
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )
            if active_from is not None and active_from < month_start:
                active_from = month_start
            if pending_from is not None and pending_from < month_start:
                pending_from = month_start
            tracker = cls(
                path,
                current_month,
                [],
                active_from,
                pending_from,
                pending_attempts,
            )
            tracker.save()
            return tracker

        return cls(
            path,
            current_month,
            outages,
            active_from,
            pending_from,
            pending_attempts,
        )

    def _roll_month(self, now: datetime) -> None:
        current = month_key(now)
        if current == self.month:
            return
        self.month = current
        self.outages = []
        month_start = now.replace(
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        if self.active_from is not None:
            self.active_from = month_start
        if self.pending_from is not None:
            self.pending_from = month_start
        self.save()

    def note_pending_failure(self, when: datetime | None = None) -> int:
        when = when or now_local()
        self._roll_month(when)
        if self.active_from is not None:
            return self.pending_attempts
        if self.pending_from is None:
            self.pending_from = when
            self.pending_attempts = 1
        else:
            self.pending_attempts += 1
        self.save()
        return self.pending_attempts

    def clear_pending(self) -> None:
        if self.pending_from is None and self.pending_attempts == 0:
            return
        self.pending_from = None
        self.pending_attempts = 0
        self.save()

    def confirm_pending(self, when: datetime | None = None) -> bool:
        when = when or now_local()
        self._roll_month(when)
        if self.active_from is not None:
            return False
        started = self.pending_from or when
        self.active_from = started
        self.pending_from = None
        self.pending_attempts = 0
        self.save()
        return True

    def start(self, when: datetime | None = None) -> bool:
        when = when or now_local()
        self._roll_month(when)
        if self.active_from is not None:
            return False
        self.active_from = when
        self.pending_from = None
        self.pending_attempts = 0
        self.save()
        return True

    def recover(self, when: datetime | None = None) -> dict[str, Any] | None:
        when = when or now_local()
        self._roll_month(when)
        if self.active_from is None:
            return None
        started = self.active_from
        seconds = max(0, int((when - started).total_seconds()))
        record = {
            "from": iso(started),
            "to": iso(when),
            "duration_seconds": seconds,
            "duration": duration_text(seconds),
        }
        self.outages.append(record)
        self.active_from = None
        self.save()
        return record

    def payload(self, when: datetime | None = None) -> dict[str, Any]:
        when = when or now_local()
        self._roll_month(when)
        rows = list(self.outages)
        total = sum(item["duration_seconds"] for item in rows)
        if self.active_from is not None:
            seconds = max(0, int((when - self.active_from).total_seconds()))
            rows.append(
                {
                    "from": iso(self.active_from),
                    "to": None,
                    "duration_seconds": seconds,
                    "duration": duration_text(seconds),
                }
            )
            total += seconds
        month_start = when.replace(
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        elapsed = max(0, int((when - month_start).total_seconds()))
        offline = min(total, elapsed)
        online = max(0, elapsed - offline)
        availability = (
            round((online / elapsed) * 100, 3)
            if elapsed > 0
            else 100.0
        )
        return {
            "state": len(rows),
            "month": self.month,
            "outages": rows,
            "total_duration_seconds": total,
            "total_duration": duration_text(total),
            "elapsed_seconds": elapsed,
            "online_seconds": online,
            "offline_seconds": offline,
            "availability_percent": availability,
        }

    def save(self) -> None:
        atomic_write_json(
            self.path,
            {
                "month": self.month,
                "outages": self.outages,
                "active_from": iso(self.active_from)
                if self.active_from is not None
                else None,
                "pending_from": iso(self.pending_from)
                if self.pending_from is not None
                else None,
                "pending_attempts": self.pending_attempts,
            },
        )
