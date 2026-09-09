from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RawProcess:
    pid: int
    create_time: float
    name: str
    cmdline: tuple[str, ...]
    cpu_time_seconds: float


@dataclass(frozen=True)
class ProcessSample:
    pid: int
    create_time: float
    name: str
    cmdline: tuple[str, ...]
    cpu_percent: float


@dataclass(frozen=True)
class ActivityState:
    plex_server_running: bool
    scanner_running: bool
    credits_detection: bool
    intro_detection: bool
    thumbnail_generation: bool
    transcoder_running: bool
    activity: str
    scanner_actions: tuple[str, ...]
    current_item: str | None
    current_items: tuple[str, ...] = ()
    transcoder_count: int = 0
    scanner_count: int = 0


@dataclass(frozen=True)
class CpuGroupMetrics:
    current: float
    average: float
    maximum: float


@dataclass(frozen=True)
class CpuMetrics:
    total: CpuGroupMetrics
    scanner: CpuGroupMetrics
    transcoder: CpuGroupMetrics


@dataclass(frozen=True)
class BuildInfo:
    version: str
    source: str
    commit: str


@dataclass(frozen=True)
class MonitorSnapshot:
    collected_at: str
    activity: ActivityState
    cpu: CpuMetrics
    process_count: int
    collector_status: str
    last_refresh: str | None


def next_last_refresh(previous: str | None, refresh: bool, collected_at: str) -> str | None:
    return collected_at if refresh else previous


def _r(value: float) -> float:
    return round(float(value), 1)


def build_state_payload(
    snapshot: MonitorSnapshot,
    build: BuildInfo,
) -> dict[str, object]:
    activity = snapshot.activity

    current_items = activity.current_items
    if not current_items and activity.current_item:
        current_items = (activity.current_item,)

    current_item = activity.current_item
    if current_item is None:
        if len(current_items) == 1:
            current_item = current_items[0]
        elif len(current_items) > 1:
            current_item = f"{len(current_items)} active items"

    return {
        "collected_at": snapshot.collected_at,
        "activity": activity.activity,
        "current_item": current_item or "none",
        "current_items": list(current_items),
        "current_item_count": len(current_items),
        "transcoder_count": activity.transcoder_count,
        "scanner_count": activity.scanner_count,
        "server_running": activity.plex_server_running,
        "scanner_running": activity.scanner_running,
        "credits_detection": activity.credits_detection,
        "intro_detection": activity.intro_detection,
        "thumbnail_generation": activity.thumbnail_generation,
        "transcoder_running": activity.transcoder_running,
        "scanner_actions": (
            ",".join(activity.scanner_actions)
            if activity.scanner_actions
            else "none"
        ),
        "process_count": snapshot.process_count,
        "collector_status": snapshot.collector_status,
        "cpu": _r(snapshot.cpu.total.current),
        "cpu_avg": _r(snapshot.cpu.total.average),
        "cpu_max": _r(snapshot.cpu.total.maximum),
        "scanner_cpu": _r(snapshot.cpu.scanner.current),
        "scanner_cpu_avg": _r(snapshot.cpu.scanner.average),
        "scanner_cpu_max": _r(snapshot.cpu.scanner.maximum),
        "transcoder_cpu": _r(snapshot.cpu.transcoder.current),
        "transcoder_cpu_avg": _r(snapshot.cpu.transcoder.average),
        "transcoder_cpu_max": _r(snapshot.cpu.transcoder.maximum),
        "last_refresh": snapshot.last_refresh,
        "build_version": build.version,
        "build_source": build.source,
        "build_commit": build.commit,
        "build_commit_short": (
            build.commit[:12] if build.commit not in {"", "unknown"} else "unknown"
        ),
    }
