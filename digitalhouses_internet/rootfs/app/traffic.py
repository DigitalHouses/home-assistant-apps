"""Monthly router traffic accounting from cumulative Home Assistant sensors."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from state import atomic_write_json, iso, now_local

TRAFFIC_HISTORY_MONTHS = 12
TRAFFIC_SCHEMA_VERSION = 1

_UNIT_FACTORS: dict[str, float] = {
    "B": 1.0,
    "kB": 1_000.0,
    "KB": 1_000.0,
    "MB": 1_000_000.0,
    "GB": 1_000_000_000.0,
    "TB": 1_000_000_000_000.0,
    "KiB": 1024.0,
    "MiB": 1024.0**2,
    "GiB": 1024.0**3,
    "TiB": 1024.0**4,
    "bit": 1.0 / 8.0,
    "kbit": 1_000.0 / 8.0,
    "Mbit": 1_000_000.0 / 8.0,
    "Gbit": 1_000_000_000.0 / 8.0,
}


def month_key(value: datetime) -> str:
    return value.astimezone().strftime("%Y-%m")


def parse_counter_state(payload: Any) -> int:
    if not isinstance(payload, dict):
        raise ValueError("Home Assistant state payload must be an object")
    raw = payload.get("state")
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"counter state is not numeric: {raw!r}") from exc
    if value < 0:
        raise ValueError("counter state must not be negative")

    attributes = payload.get("attributes")
    if not isinstance(attributes, dict):
        attributes = {}
    unit = str(attributes.get("unit_of_measurement") or "B").strip()
    factor = _UNIT_FACTORS.get(unit)
    if factor is None:
        raise ValueError(f"unsupported traffic counter unit: {unit!r}")
    return max(0, int(round(value * factor)))


def _delta(current: int, previous: int) -> int:
    if current >= previous:
        return current - previous
    # Source counter reset (typically router/integration restart).
    return current


@dataclass
class TrafficStore:
    path: Path
    months: dict[str, dict[str, int]]
    last_month: str | None
    last_download_bytes: int | None
    last_upload_bytes: int | None
    last_sample_at: str | None

    @classmethod
    def load(cls, path: Path) -> "TrafficStore":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            raw = {}
        if not isinstance(raw, dict):
            raw = {}

        months_raw = raw.get("months")
        months: dict[str, dict[str, int]] = {}
        if isinstance(months_raw, dict):
            for key, value in months_raw.items():
                if not isinstance(key, str) or not isinstance(value, dict):
                    continue
                try:
                    download = max(0, int(value.get("download_bytes", 0)))
                    upload = max(0, int(value.get("upload_bytes", 0)))
                except (TypeError, ValueError):
                    continue
                months[key] = {
                    "download_bytes": download,
                    "upload_bytes": upload,
                }

        last = raw.get("last")
        if not isinstance(last, dict):
            last = {}

        def optional_int(name: str) -> int | None:
            value = last.get(name)
            if value is None:
                return None
            try:
                return max(0, int(value))
            except (TypeError, ValueError):
                return None

        store = cls(
            path=path,
            months=months,
            last_month=(
                str(last.get("month"))
                if isinstance(last.get("month"), str)
                else None
            ),
            last_download_bytes=optional_int("download_bytes"),
            last_upload_bytes=optional_int("upload_bytes"),
            last_sample_at=(
                str(last.get("sampled_at"))
                if isinstance(last.get("sampled_at"), str)
                else None
            ),
        )
        store._trim()
        return store

    def _trim(self) -> None:
        keep = sorted(self.months)[-TRAFFIC_HISTORY_MONTHS:]
        self.months = {key: self.months[key] for key in keep}

    def update(
        self,
        download_bytes: int,
        upload_bytes: int,
        when: datetime | None = None,
    ) -> None:
        when = when or now_local()
        month = month_key(when)
        bucket = self.months.setdefault(
            month,
            {"download_bytes": 0, "upload_bytes": 0},
        )

        if (
            self.last_month == month
            and self.last_download_bytes is not None
            and self.last_upload_bytes is not None
        ):
            bucket["download_bytes"] += _delta(
                download_bytes, self.last_download_bytes
            )
            bucket["upload_bytes"] += _delta(
                upload_bytes, self.last_upload_bytes
            )

        # At a calendar-month boundary the first sample establishes the new
        # baseline. This avoids assigning an unknown cross-boundary delta to the
        # wrong month. With the normal 60 s poll, continuous operation loses at
        # most one polling interval at the boundary.
        self.last_month = month
        self.last_download_bytes = download_bytes
        self.last_upload_bytes = upload_bytes
        self.last_sample_at = iso(when)
        self._trim()
        self.save()

    def payload(
        self,
        *,
        configured: bool,
        available: bool,
        download_entity_id: str,
        upload_entity_id: str,
        when: datetime | None = None,
    ) -> dict[str, Any]:
        when = when or now_local()
        month = month_key(when)
        bucket = self.months.get(
            month,
            {"download_bytes": 0, "upload_bytes": 0},
        )

        def gib(value: int) -> float:
            return round(value / (1024.0**3), 3)

        history = []
        for key in sorted(self.months, reverse=True)[:TRAFFIC_HISTORY_MONTHS]:
            item = self.months[key]
            download = int(item.get("download_bytes", 0))
            upload = int(item.get("upload_bytes", 0))
            history.append(
                {
                    "month": key,
                    "download_gib": gib(download),
                    "upload_gib": gib(upload),
                    "total_gib": gib(download + upload),
                }
            )

        download = int(bucket.get("download_bytes", 0))
        upload = int(bucket.get("upload_bytes", 0))
        return {
            "configured": configured,
            "available": available,
            "month": month,
            "download_gib": gib(download),
            "upload_gib": gib(upload),
            "total_gib": gib(download + upload),
            "months": history,
            "history_count": len(history),
            "last_update": self.last_sample_at,
            "download_source": download_entity_id,
            "upload_source": upload_entity_id,
        }

    def save(self) -> None:
        atomic_write_json(
            self.path,
            {
                "schema_version": TRAFFIC_SCHEMA_VERSION,
                "months": self.months,
                "last": {
                    "month": self.last_month,
                    "download_bytes": self.last_download_bytes,
                    "upload_bytes": self.last_upload_bytes,
                    "sampled_at": self.last_sample_at,
                },
            },
        )
