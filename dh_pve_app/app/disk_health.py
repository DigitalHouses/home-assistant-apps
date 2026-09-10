from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from .collectors.smart import SmartSnapshot


class DiskHealthState(str, Enum):
    HEALTHY = "HEALTHY"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class DiskHealthResult:
    state: DiskHealthState
    reasons: tuple[str, ...]
    recommendation: str | None


_CONCERNING = (
    "media_errors", "reallocated_sectors", "pending_sectors", "offline_uncorrectable",
    "uncorrectable_errors", "program_failures", "erase_failures", "runtime_bad_blocks",
)


def _positive(value):
    return value is not None and value > 0


def _grew(current, previous: dict[str, int | float] | None, key: str) -> bool:
    if previous is None:
        return False
    old = previous.get(key)
    value = getattr(current, key)
    return old is not None and value is not None and value > old


def evaluate_disk_health(snapshot: SmartSnapshot, previous: dict[str, int | float] | None = None) -> DiskHealthResult:
    critical: list[str] = []
    warning: list[str] = []

    if snapshot.smart_passed is False:
        critical.append("smart_failed")
    if _positive(snapshot.critical_warning):
        critical.append("nvme_critical_warning")
    if snapshot.wear_used_percent is not None:
        if snapshot.wear_used_percent >= 90:
            critical.append("wearout")
        elif snapshot.wear_used_percent >= 70:
            warning.append("wearout")

    for key in _CONCERNING:
        if _positive(getattr(snapshot, key)):
            if _grew(snapshot, previous, key):
                critical.append(key + "_growth")
            else:
                warning.append(key)

    if _grew(snapshot, previous, "unsafe_shutdowns"):
        warning.append("unsafe_shutdown_growth")

    warn_temp, crit_temp = {
        "HDD": (50.0, 60.0),
        "SSD": (70.0, 80.0),
        "NVMe": (75.0, 85.0),
    }.get(snapshot.disk_type, (70.0, 85.0))
    if snapshot.temperature_c is not None:
        if snapshot.temperature_c >= crit_temp:
            critical.append("temperature")
        elif snapshot.temperature_c >= warn_temp:
            warning.append("temperature")

    if critical:
        recommendation = "Срочно проверить резервную копию и подготовить замену диска"
        if critical == ["wearout"]:
            recommendation = "Подготовить замену диска"
        return DiskHealthResult(DiskHealthState.CRITICAL, tuple(dict.fromkeys(critical)), recommendation)
    if warning:
        if "wearout" in warning:
            recommendation = "Запланировать замену диска"
        elif "unsafe_shutdown_growth" in warning:
            recommendation = "Проверить питание сервера и корректность выключения"
        else:
            recommendation = "Проверить SMART и наблюдать динамику показателей"
        return DiskHealthResult(DiskHealthState.WARNING, tuple(dict.fromkeys(warning)), recommendation)
    return DiskHealthResult(DiskHealthState.HEALTHY, (), None)
