"""Persistent current-month outage state."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


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


@dataclass
class RecoveryRuntimeState:
    stopped: bool = False
    cycle: int = 0
    cooldown_until: datetime | None = None

    @classmethod
    def load(cls, path: Path) -> "RecoveryRuntimeState":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return cls()
        if not isinstance(raw, dict):
            return cls()

        cooldown_until = None
        raw_deadline = raw.get("cooldown_until")
        if isinstance(raw_deadline, str) and raw_deadline:
            try:
                cooldown_until = datetime.fromisoformat(raw_deadline)
                if cooldown_until.tzinfo is None:
                    cooldown_until = cooldown_until.replace(
                        tzinfo=now_local().tzinfo
                    )
            except ValueError:
                cooldown_until = None

        try:
            cycle = max(0, int(raw.get("cycle") or 0))
        except (TypeError, ValueError):
            cycle = 0

        return cls(
            stopped=bool(raw.get("stopped")),
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

    @classmethod
    def load(cls, path: Path) -> "OutageTracker":
        now = now_local()
        current_month = month_key(now)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            raw = {}

        if not isinstance(raw, dict):
            raw = {}

        active_from = None
        active_raw = raw.get("active_from")
        if isinstance(active_raw, str) and active_raw:
            try:
                active_from = datetime.fromisoformat(active_raw)
                if active_from.tzinfo is None:
                    active_from = active_from.replace(tzinfo=now.tzinfo)
            except ValueError:
                active_from = None

        if raw.get("month") != current_month:
            month_start = now.replace(
                day=1,
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )
            if active_from is not None and active_from < month_start:
                active_from = month_start
            tracker = cls(path, current_month, [], active_from)
            tracker.save()
            return tracker

        outages = raw.get("outages")
        if not isinstance(outages, list):
            outages = []
        return cls(path, current_month, outages, active_from)

    def _roll_month(self, now: datetime) -> None:
        current = month_key(now)
        if current == self.month:
            return
        self.month = current
        self.outages = []
        if self.active_from is not None:
            self.active_from = now.replace(
                day=1,
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )
        self.save()

    def start(self, when: datetime | None = None) -> bool:
        when = when or now_local()
        self._roll_month(when)
        if self.active_from is not None:
            return False
        self.active_from = when
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
        total = sum(int(item.get("duration_seconds", 0)) for item in rows)
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
            },
        )
