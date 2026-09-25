from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from .collectors.smart import SmartSnapshot


@dataclass(frozen=True)
class DailyDiskStats:
    day: str
    max_temperature_c: float | None
    power_on_hours: int | None
    wear_used_percent: float | None
    media_errors: int | None
    reallocated_sectors: int | None
    pending_sectors: int | None
    offline_uncorrectable: int | None
    unsafe_shutdowns: int | None
    data_written_tb: float | None


def _from_snapshot(snapshot: SmartSnapshot, day: str) -> DailyDiskStats:
    return DailyDiskStats(
        day=day,
        max_temperature_c=snapshot.temperature_c,
        power_on_hours=snapshot.power_on_hours,
        wear_used_percent=snapshot.wear_used_percent,
        media_errors=snapshot.media_errors,
        reallocated_sectors=snapshot.reallocated_sectors,
        pending_sectors=snapshot.pending_sectors,
        offline_uncorrectable=snapshot.offline_uncorrectable,
        unsafe_shutdowns=snapshot.unsafe_shutdowns,
        data_written_tb=snapshot.data_written_tb,
    )


def update_daily_stats(current: DailyDiskStats | None, snapshot: SmartSnapshot, observed_at: datetime) -> tuple[DailyDiskStats, DailyDiskStats | None]:
    day = observed_at.date().isoformat()
    if current is None:
        return _from_snapshot(snapshot, day), None
    if current.day != day:
        return _from_snapshot(snapshot, day), current
    temps = [v for v in (current.max_temperature_c, snapshot.temperature_c) if v is not None]
    return DailyDiskStats(
        day=day,
        max_temperature_c=max(temps) if temps else None,
        power_on_hours=snapshot.power_on_hours,
        wear_used_percent=snapshot.wear_used_percent,
        media_errors=snapshot.media_errors,
        reallocated_sectors=snapshot.reallocated_sectors,
        pending_sectors=snapshot.pending_sectors,
        offline_uncorrectable=snapshot.offline_uncorrectable,
        unsafe_shutdowns=snapshot.unsafe_shutdowns,
        data_written_tb=snapshot.data_written_tb,
    ), None
