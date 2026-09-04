from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def iso_from_epoch(value: float | int | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(float(value), ZoneInfo("UTC")).isoformat().replace("+00:00", "Z")


def last_age_seconds(last_ts: float | int | None, now_ts: float) -> int | None:
    if last_ts is None:
        return None
    return max(0, int(float(now_ts) - float(last_ts)))


def records_k(count: int | None) -> float | None:
    if count is None:
        return None
    return round(int(count) / 1000.0, 1)


def db_depth_days(start_ts: float | int | None, now_ts: float, timezone_name: str) -> int | None:
    if start_ts is None:
        return None
    tz = ZoneInfo(timezone_name)
    start_date = datetime.fromtimestamp(float(start_ts), tz).date()
    now_date = datetime.fromtimestamp(float(now_ts), tz).date()
    return max(0, (now_date - start_date).days)


def yesterday_bounds_epoch(now_ts: float, timezone_name: str) -> tuple[float, float]:
    tz = ZoneInfo(timezone_name)
    now_local = datetime.fromtimestamp(float(now_ts), tz)
    today_start = datetime.combine(now_local.date(), datetime.min.time(), tzinfo=tz)
    yesterday_start = today_start - timedelta(days=1)
    return yesterday_start.timestamp(), today_start.timestamp()
