from __future__ import annotations

from collections.abc import Mapping

from ..models import HardwareIdentity


_PLACEHOLDERS = {
    "",
    "unknown",
    "none",
    "n/a",
    "na",
    "not specified",
    "not available",
    "default string",
    "to be filled by o.e.m.",
    "to be filled by oem",
    "system manufacturer",
    "system product name",
    "system version",
    "o.e.m.",
    "oem",
}


def clean_dmi_value(value: str | None) -> str | None:
    if value is None:
        return None
    clean = value.replace("\x00", "").replace("\r", "").strip()
    if clean.lower() in _PLACEHOLDERS:
        return None
    return clean


def build_hardware_identity(values: Mapping[str, str | None]) -> HardwareIdentity:
    system_vendor = clean_dmi_value(values.get("sys_vendor"))
    system_model = clean_dmi_value(values.get("product_name"))
    system_version = clean_dmi_value(values.get("product_version"))
    board_vendor = clean_dmi_value(values.get("board_vendor"))
    board_model = clean_dmi_value(values.get("board_name"))
    board_version = clean_dmi_value(values.get("board_version"))

    if system_model:
        manufacturer = system_vendor or board_vendor
        model = system_model
        product_version = system_version
        source = "system" if system_vendor else "system_with_board_vendor"
    elif board_model:
        manufacturer = board_vendor or system_vendor
        model = board_model
        product_version = board_version
        source = "board_fallback"
    else:
        manufacturer = None
        model = None
        product_version = None
        source = "unavailable"

    return HardwareIdentity(
        manufacturer=manufacturer,
        model=model,
        product_version=product_version,
        hardware_source=source,
        system_vendor=system_vendor,
        system_model=system_model,
        system_version=system_version,
        board_vendor=board_vendor,
        board_model=board_model,
        board_version=board_version,
    )


def parse_pve_manager_version(text: str) -> str | None:
    for line in text.splitlines():
        if not line.startswith("pve-manager:"):
            continue
        value = line.split(":", 1)[1].strip()
        if not value:
            return None
        return value.split()[0]
    return None
