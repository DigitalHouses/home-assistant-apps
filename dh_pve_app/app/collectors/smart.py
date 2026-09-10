from __future__ import annotations
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SmartSnapshot:
    device_path: str
    protocol: str | None
    disk_type: str
    model: str | None
    serial: str | None
    wwn: str | None
    firmware: str | None
    capacity_bytes: int | None
    smart_available: bool
    smart_passed: bool | None
    smartctl_exit_status: int | None
    temperature_c: float | None
    temperature_max_c: float | None
    power_on_hours: int | None
    power_cycles: int | None
    wear_used_percent: float | None
    life_remaining_percent: float | None
    available_spare_percent: float | None
    available_spare_threshold_percent: float | None
    data_written_tb: float | None
    critical_warning: int | None
    media_errors: int | None
    error_log_entries: int | None
    unsafe_shutdowns: int | None
    reallocated_sectors: int | None
    pending_sectors: int | None
    offline_uncorrectable: int | None
    uncorrectable_errors: int | None
    program_failures: int | None
    erase_failures: int | None
    runtime_bad_blocks: int | None
    crc_errors: int | None


def _num(value: Any) -> int | float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _ata_attributes(data: dict) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for item in data.get("ata_smart_attributes", {}).get("table", []) or []:
        name = item.get("name")
        if isinstance(name, str):
            result[name] = item
    return result


def _raw(attrs: dict[str, dict], names: tuple[str, ...]) -> int | float | None:
    for name in names:
        item = attrs.get(name)
        if not item:
            continue
        value = item.get("raw", {}).get("value")
        if _num(value) is not None:
            return value
    return None


def _norm(attrs: dict[str, dict], names: tuple[str, ...]) -> int | float | None:
    for name in names:
        item = attrs.get(name)
        if not item:
            continue
        value = item.get("value")
        if _num(value) is not None:
            return value
    return None


def smart_wwn(data: dict) -> str | None:
    wwn = data.get("wwn")
    if isinstance(wwn, str) and wwn.strip():
        return wwn.strip()
    if isinstance(wwn, dict):
        naa = _num(wwn.get("naa")); oui = _num(wwn.get("oui")); ident = _num(wwn.get("id"))
        if all(isinstance(v, int) for v in (naa, oui, ident)):
            value = (naa << 60) | (oui << 36) | ident
            return f"naa.{value:016x}"
    for ns in data.get("nvme_namespaces", []) or []:
        eui = ns.get("eui64")
        if isinstance(eui, dict):
            oui = _num(eui.get("oui")); ext_id = _num(eui.get("ext_id"))
            if isinstance(oui, int) and isinstance(ext_id, int):
                value = (oui << 40) | ext_id
                return f"eui.{value:016x}"
    return None


def _disk_type(data: dict) -> str:
    protocol = str(data.get("device", {}).get("protocol") or "").upper()
    rotation = _num(data.get("rotation_rate"))
    if rotation and rotation > 0:
        return "HDD"
    if protocol == "NVME":
        return "NVMe"
    return "SSD"


def parse_smart_json(data: dict, device_path: str) -> SmartSnapshot:
    attrs = _ata_attributes(data)
    nvme = data.get("nvme_smart_health_information_log", {}) or {}
    protocol = data.get("device", {}).get("protocol")
    smart_available = bool(data.get("smart_support", {}).get("available", data.get("smart_status", {}).get("passed") is not None))
    smart_passed = data.get("smart_status", {}).get("passed")
    if not isinstance(smart_passed, bool):
        smart_passed = None

    temp_candidates: list[float] = []
    for value in [data.get("temperature", {}).get("current"), nvme.get("temperature"), *(nvme.get("temperature_sensors") or [])]:
        if _num(value) is not None:
            temp_candidates.append(float(value))
    current_temp = None
    if _num(data.get("temperature", {}).get("current")) is not None:
        current_temp = float(data["temperature"]["current"])
    elif _num(nvme.get("temperature")) is not None:
        current_temp = float(nvme["temperature"])
    elif temp_candidates:
        current_temp = temp_candidates[0]

    life_remaining = _norm(attrs, (
        "Wear_Leveling_Count", "Percent_Lifetime_Remain", "Remaining_Lifetime_Perc",
        "SSD_Life_Left", "Media_Wearout_Indicator"
    ))
    ata_used = _raw(attrs, ("Percentage_Used", "Percent_Lifetime_Used"))
    wear = _num(nvme.get("percentage_used"))
    if wear is None:
        wear = ata_used
    if wear is None and life_remaining is not None:
        wear = 100 - float(life_remaining)

    nvme_units = _num(nvme.get("data_units_written"))
    ata_lbas = _raw(attrs, ("Total_LBAs_Written",))
    data_written_tb = None
    if nvme_units is not None:
        data_written_tb = round(float(nvme_units) * 512000 / 1_000_000_000_000, 2)
    elif ata_lbas is not None:
        block = _num(data.get("logical_block_size")) or 512
        data_written_tb = round(float(ata_lbas) * float(block) / 1_000_000_000_000, 2)

    power_on_hours = _num(data.get("power_on_time", {}).get("hours"))
    if power_on_hours is None:
        power_on_hours = _num(nvme.get("power_on_hours"))
    if power_on_hours is None:
        power_on_hours = _raw(attrs, ("Power_On_Hours",))

    power_cycles = _num(data.get("power_cycle_count"))
    if power_cycles is None:
        power_cycles = _num(nvme.get("power_cycles"))
    if power_cycles is None:
        power_cycles = _raw(attrs, ("Power_Cycle_Count",))

    def raw_int(names: tuple[str, ...]) -> int | None:
        value = _raw(attrs, names)
        return int(value) if value is not None else None

    ata_error_count = data.get("ata_smart_error_log", {}).get("summary", {}).get("count")

    return SmartSnapshot(
        device_path=device_path,
        protocol=str(protocol) if protocol is not None else None,
        disk_type=_disk_type(data),
        model=data.get("model_name") or data.get("scsi_model_name"),
        serial=data.get("serial_number"),
        wwn=smart_wwn(data),
        firmware=data.get("firmware_version"),
        capacity_bytes=int(data["user_capacity"]["bytes"]) if _num(data.get("user_capacity", {}).get("bytes")) is not None else None,
        smart_available=smart_available,
        smart_passed=smart_passed,
        smartctl_exit_status=int(data["smartctl"]["exit_status"]) if _num(data.get("smartctl", {}).get("exit_status")) is not None else None,
        temperature_c=current_temp,
        temperature_max_c=max(temp_candidates) if temp_candidates else None,
        power_on_hours=int(power_on_hours) if power_on_hours is not None else None,
        power_cycles=int(power_cycles) if power_cycles is not None else None,
        wear_used_percent=float(wear) if wear is not None else None,
        life_remaining_percent=float(life_remaining) if life_remaining is not None else None,
        available_spare_percent=float(nvme["available_spare"]) if _num(nvme.get("available_spare")) is not None else None,
        available_spare_threshold_percent=float(nvme["available_spare_threshold"]) if _num(nvme.get("available_spare_threshold")) is not None else None,
        data_written_tb=data_written_tb,
        critical_warning=int(nvme["critical_warning"]) if _num(nvme.get("critical_warning")) is not None else None,
        media_errors=int(nvme["media_errors"]) if _num(nvme.get("media_errors")) is not None else None,
        error_log_entries=int(nvme["num_err_log_entries"]) if _num(nvme.get("num_err_log_entries")) is not None else int(ata_error_count) if _num(ata_error_count) is not None else None,
        unsafe_shutdowns=int(nvme["unsafe_shutdowns"]) if _num(nvme.get("unsafe_shutdowns")) is not None else None,
        reallocated_sectors=raw_int(("Reallocated_Sector_Ct",)),
        pending_sectors=raw_int(("Current_Pending_Sector",)),
        offline_uncorrectable=raw_int(("Offline_Uncorrectable",)),
        uncorrectable_errors=raw_int(("Uncorrectable_Error_Cnt", "Reported_Uncorrect")),
        program_failures=raw_int(("Program_Fail_Cnt_Total", "Program_Fail_Count_Chip")),
        erase_failures=raw_int(("Erase_Fail_Count_Total", "Erase_Fail_Count_Chip")),
        runtime_bad_blocks=raw_int(("Runtime_Bad_Block",)),
        crc_errors=raw_int(("CRC_Error_Count", "UDMA_CRC_Error_Count")),
    )
