from __future__ import annotations

from dataclasses import dataclass

KIB_PER_GIB = 1024 * 1024


@dataclass(frozen=True)
class StorageSnapshot:
    name: str
    storage_type: str
    status: str
    total_kib: int
    used_kib: int
    available_kib: int
    total_gib: float
    used_gib: float
    available_gib: float
    usage_percent: float


def _kib_to_gib(value: int) -> float:
    return round(value / KIB_PER_GIB, 2)


def parse_pvesm_status(text: str) -> tuple[StorageSnapshot, ...]:
    items: list[StorageSnapshot] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("Name "):
            continue

        parts = line.split()
        if len(parts) < 7:
            continue

        name, storage_type, status = parts[0], parts[1], parts[2]
        try:
            total = int(parts[3])
            used = int(parts[4])
            available = int(parts[5])
            reported_usage = float(parts[6].rstrip("%"))
        except ValueError:
            continue

        # pvesm reports capacities in KiB. Expose ready-to-use GiB values so
        # Home Assistant does not need templates to calculate infrastructure data.
        usage = round(used * 100.0 / total, 2) if total > 0 else reported_usage

        items.append(
            StorageSnapshot(
                name=name,
                storage_type=storage_type,
                status=status,
                total_kib=total,
                used_kib=used,
                available_kib=available,
                total_gib=_kib_to_gib(total),
                used_gib=_kib_to_gib(used),
                available_gib=_kib_to_gib(available),
                usage_percent=usage,
            )
        )

    return tuple(items)
