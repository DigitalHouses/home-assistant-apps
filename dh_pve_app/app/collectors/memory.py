from __future__ import annotations

from pathlib import Path

from ..models import MemorySnapshot


def _parse_kib_fields(text: str) -> dict[str, int]:
    values: dict[str, int] = {}
    for raw in text.splitlines():
        if ":" not in raw:
            continue
        key, rest = raw.split(":", 1)
        token = rest.strip().split()
        if not token:
            continue
        try:
            values[key] = int(token[0])
        except ValueError:
            continue
    return values


def parse_meminfo(text: str) -> MemorySnapshot:
    values = _parse_kib_fields(text)
    required = ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree")
    missing = [name for name in required if name not in values]
    if missing:
        raise ValueError(f"missing /proc/meminfo fields: {', '.join(missing)}")

    total = values["MemTotal"]
    available = values["MemAvailable"]
    swap_total = values["SwapTotal"]
    swap_free = values["SwapFree"]
    if total <= 0:
        raise ValueError("MemTotal must be greater than zero")

    used = max(0, total - available)
    swap_used = max(0, swap_total - swap_free)
    usage = round(used * 100.0 / total, 1)
    swap_usage = round(swap_used * 100.0 / swap_total, 1) if swap_total > 0 else 0.0

    return MemorySnapshot(
        total_kib=total,
        available_kib=available,
        used_kib=used,
        usage_percent=usage,
        swap_total_kib=swap_total,
        swap_free_kib=swap_free,
        swap_used_kib=swap_used,
        swap_usage_percent=swap_usage,
    )


def collect_memory(path: Path = Path("/proc/meminfo")) -> MemorySnapshot:
    return parse_meminfo(path.read_text(encoding="utf-8"))
