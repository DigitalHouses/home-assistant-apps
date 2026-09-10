from __future__ import annotations

import re
import subprocess
from pathlib import Path

from ..models import MemoryInventory, MemoryModule, MemorySnapshot


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


_DMI_PLACEHOLDERS = {
    "",
    "unknown",
    "not specified",
    "not provided",
    "to be filled by o.e.m.",
    "default string",
    "0x0000",
}


def _clean_dmi_value(raw: str | None) -> str | None:
    if raw is None:
        return None
    value = raw.strip()
    if value.lower() in _DMI_PLACEHOLDERS:
        return None
    return value


def _parse_size_gib(raw: str) -> float | None:
    value = raw.strip()
    if value.lower() == "no module installed":
        return None
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*(KB|MB|GB|TB)", value, re.I)
    if not match:
        return None
    amount = float(match.group(1))
    unit = match.group(2).upper()
    scale = {"KB": 1 / (1024 * 1024), "MB": 1 / 1024, "GB": 1, "TB": 1024}
    return round(amount * scale[unit], 3)


def _parse_speed_mt_s(raw: str | None) -> int | None:
    value = _clean_dmi_value(raw)
    if value is None:
        return None
    match = re.match(r"^([0-9]+)\s*(?:MT/s|MHz)\b", value, re.I)
    return int(match.group(1)) if match else None


def _common_value(values):
    unique = {value for value in values if value is not None}
    if len(unique) == 1:
        return next(iter(unique))
    return None


def parse_dmidecode_memory(text: str) -> MemoryInventory:
    blocks = re.split(r"(?m)^Memory Device\s*$", text)[1:]
    modules: list[MemoryModule] = []
    total_slots = 0

    for block in blocks:
        fields: dict[str, str] = {}
        for raw_line in block.splitlines():
            match = re.match(r"^\s*([^:]+):\s*(.*)$", raw_line)
            if match:
                fields[match.group(1).strip()] = match.group(2).strip()

        if "Size" not in fields:
            continue

        total_slots += 1
        size_gib = _parse_size_gib(fields["Size"])
        if size_gib is None:
            continue

        modules.append(
            MemoryModule(
                locator=_clean_dmi_value(fields.get("Locator")),
                bank_locator=_clean_dmi_value(fields.get("Bank Locator")),
                size_gib=size_gib,
                form_factor=_clean_dmi_value(fields.get("Form Factor")),
                memory_type=_clean_dmi_value(fields.get("Type")),
                speed_mt_s=_parse_speed_mt_s(fields.get("Speed")),
                configured_speed_mt_s=_parse_speed_mt_s(
                    fields.get("Configured Memory Speed")
                ),
                manufacturer=_clean_dmi_value(fields.get("Manufacturer")),
                part_number=_clean_dmi_value(fields.get("Part Number")),
            )
        )

    return MemoryInventory(
        total_slots=total_slots,
        populated_slots=len(modules),
        total_gib=round(sum(module.size_gib for module in modules), 3),
        memory_type=_common_value(module.memory_type for module in modules),
        form_factor=_common_value(module.form_factor for module in modules),
        speed_mt_s=_common_value(module.speed_mt_s for module in modules),
        configured_speed_mt_s=_common_value(
            module.configured_speed_mt_s for module in modules
        ),
        modules=tuple(modules),
    )


def collect_memory_inventory(*, run=subprocess.run) -> MemoryInventory:
    result = run(
        ["dmidecode", "-t", "memory"],
        check=True,
        capture_output=True,
        text=True,
    )
    return parse_dmidecode_memory(result.stdout)
