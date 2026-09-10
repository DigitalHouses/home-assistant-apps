from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class StorageSnapshot:
    name: str
    storage_type: str
    status: str
    total_kib: int
    used_kib: int
    available_kib: int
    usage_percent: float

def parse_pvesm_status(text: str) -> tuple[StorageSnapshot, ...]:
    items = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("Name "):
            continue
        parts = line.split()
        if len(parts) < 7:
            continue
        name, storage_type, status = parts[0], parts[1], parts[2]
        try:
            total = int(parts[3]); used = int(parts[4]); available = int(parts[5])
            usage = float(parts[6].rstrip("%"))
        except ValueError:
            continue
        items.append(StorageSnapshot(name, storage_type, status, total, used, available, usage))
    return tuple(items)
