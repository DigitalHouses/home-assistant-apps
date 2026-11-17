from __future__ import annotations

"""Read-only RPM source for the experimentally verified GMKtec NucBox K15.

The four EC bytes at 0x35..0x38 are K15-specific; never probe other systems.
There is deliberately no PWM, write API, or calibration capability here.
"""

from pathlib import Path

from .collectors.cooling import FanSnapshot

MODEL = "NucBox_K15"
EC_OFFSET = 0x35
MAX_RPM = 12000
MAX_IMMEDIATE_DELTA_RPM = 300


def is_k15(dmi_root: Path = Path("/sys/class/dmi/id")) -> bool:
    try:
        return (dmi_root / "product_name").read_text(encoding="ascii").strip() == MODEL
    except (OSError, UnicodeError):
        return False


def read_k15_ec_rpm(
    *,
    ec_file: Path = Path("/sys/kernel/debug/ec/ec0/io"),
    write_support_file: Path = Path("/sys/module/ec_sys/parameters/write_support"),
) -> tuple[int | None, int | None]:
    """Return (CPU, second channel) or unavailable, never guessed zero.

    Each sample is double-read to reject a torn EC multi-byte observation.
    Two bounded 4-byte reads are performed only during the existing fan cycle.
    """
    try:
        # Refuse observation if kernel EC write support has been enabled.
        if write_support_file.read_text(encoding="ascii").strip() != "N":
            return None, None
        with ec_file.open("rb") as stream:
            stream.seek(EC_OFFSET)
            first = stream.read(4)
            stream.seek(EC_OFFSET)
            second = stream.read(4)
    except (OSError, ValueError, UnicodeError):
        return None, None
    if len(first) != 4 or len(second) != 4:
        return None, None
    a = (int.from_bytes(first[:2], "big"), int.from_bytes(first[2:], "big"))
    b = (int.from_bytes(second[:2], "big"), int.from_bytes(second[2:], "big"))
    if not all(
        0 <= x <= MAX_RPM and 0 <= y <= MAX_RPM
        and abs(x - y) <= MAX_IMMEDIATE_DELTA_RPM
        for x, y in zip(a, b)
    ):
        return None, None
    # Both fans at 0 is more likely an unreadable/reset EC than valid tach data.
    if b == (0, 0):
        return None, None
    return b


def collect_k15_ec_fans(
    *,
    dmi_root: Path = Path("/sys/class/dmi/id"),
    ec_file: Path = Path("/sys/kernel/debug/ec/ec0/io"),
    write_support_file: Path = Path("/sys/module/ec_sys/parameters/write_support"),
) -> tuple[FanSnapshot, ...]:
    if not is_k15(dmi_root):
        return ()
    rpms = read_k15_ec_rpm(ec_file=ec_file, write_support_file=write_support_file)
    return tuple(
        FanSnapshot(
            fan_id=f"gmktec_k15_ec_ec0_fan{index}",
            chip="gmktec_k15_ec",
            chip_display_name="GMKtec K15 EC",
            source_device="ec0",
            fan_name=f"fan{index}",
            fan_index=index,
            label=label,
            display_name=f"{label} RPM - GMKtec K15 EC",
            rpm=rpm,
            available=rpm is not None,
            input_path=str(ec_file),
        )
        for index, label, rpm in ((1, "CPU FAN", rpms[0]), (2, "FAN2", rpms[1]))
    )
