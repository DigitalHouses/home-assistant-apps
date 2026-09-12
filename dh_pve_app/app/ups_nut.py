from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Callable

from .config import UpsConfig
from .publish_policy import MetricValue


class NutReadError(RuntimeError):
    """Raised when a read-only NUT query cannot be completed."""


@dataclass(frozen=True)
class UpsSnapshot:
    raw: dict[str, str]
    manufacturer: str | None
    model: str | None
    serial: str | None
    driver_name: str | None
    driver_version: str | None
    driver_data: str | None
    status_raw: str
    status_tokens: tuple[str, ...]
    line_power: bool
    on_battery: bool
    low_battery: bool
    replace_battery: bool
    overload: bool
    bypass: bool
    charging: bool
    discharging: bool
    battery_charge_percent: float | None
    runtime_seconds: float | None
    battery_voltage_v: float | None
    battery_nominal_voltage_v: float | None
    load_percent: float | None
    nominal_real_power_w: float | None
    input_voltage_v: float | None
    input_nominal_voltage_v: float | None
    output_voltage_v: float | None
    input_transfer_high_v: float | None
    input_transfer_low_v: float | None
    warning_charge_percent: float | None
    low_charge_percent: float | None
    low_runtime_seconds: float | None
    test_result: str | None
    beeper_status: str | None


def _optional_text(raw: dict[str, str], *keys: str) -> str | None:
    for key in keys:
        value = raw.get(key)
        if value is not None:
            value = value.strip()
            if value:
                return value
    return None


def _optional_float(raw: dict[str, str], key: str) -> float | None:
    value = raw.get(key)
    if value is None:
        return None
    try:
        return float(value.strip())
    except (TypeError, ValueError):
        return None


def _positive_float(raw: dict[str, str], key: str) -> float | None:
    value = _optional_float(raw, key)
    if value is None or value <= 0:
        return None
    return value


def parse_upsc_output(text: str) -> UpsSnapshot:
    raw: dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if not key:
            continue
        raw[key] = value.strip()

    status_raw = raw.get("ups.status", "").strip()
    status_tokens = tuple(token for token in status_raw.split() if token)
    token_set = set(status_tokens)

    return UpsSnapshot(
        raw=raw,
        manufacturer=_optional_text(raw, "device.mfr", "ups.mfr"),
        model=_optional_text(raw, "device.model", "ups.model"),
        serial=_optional_text(raw, "device.serial", "ups.serial"),
        driver_name=_optional_text(raw, "driver.name"),
        driver_version=_optional_text(raw, "driver.version"),
        driver_data=_optional_text(raw, "driver.version.data"),
        status_raw=status_raw,
        status_tokens=status_tokens,
        line_power="OL" in token_set,
        on_battery="OB" in token_set,
        low_battery="LB" in token_set,
        replace_battery="RB" in token_set,
        overload="OVER" in token_set,
        bypass="BYPASS" in token_set,
        charging="CHRG" in token_set,
        discharging="DISCHRG" in token_set,
        battery_charge_percent=_optional_float(raw, "battery.charge"),
        runtime_seconds=_optional_float(raw, "battery.runtime"),
        battery_voltage_v=_optional_float(raw, "battery.voltage"),
        battery_nominal_voltage_v=_optional_float(raw, "battery.voltage.nominal"),
        load_percent=_optional_float(raw, "ups.load"),
        nominal_real_power_w=_optional_float(raw, "ups.realpower.nominal"),
        input_voltage_v=_optional_float(raw, "input.voltage"),
        input_nominal_voltage_v=_optional_float(raw, "input.voltage.nominal"),
        output_voltage_v=_optional_float(raw, "output.voltage"),
        input_transfer_high_v=_positive_float(raw, "input.transfer.high"),
        input_transfer_low_v=_positive_float(raw, "input.transfer.low"),
        warning_charge_percent=_optional_float(raw, "battery.charge.warning"),
        low_charge_percent=_optional_float(raw, "battery.charge.low"),
        low_runtime_seconds=_optional_float(raw, "battery.runtime.low"),
        test_result=_optional_text(raw, "ups.test.result"),
        beeper_status=_optional_text(raw, "ups.beeper.status"),
    )


def read_ups(
    config: UpsConfig,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> UpsSnapshot:
    command = ["upsc", f"{config.name}@{config.host}:{config.port}"]
    try:
        completed = runner(
            command,
            capture_output=True,
            text=True,
            timeout=config.command_timeout_seconds,
            check=True,
        )
    except FileNotFoundError as exc:
        raise NutReadError("Команда upsc не найдена") from exc
    except subprocess.TimeoutExpired as exc:
        raise NutReadError("Истекло время ожидания ответа NUT") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip()
        if detail:
            raise NutReadError(f"NUT вернул ошибку: {detail}") from exc
        raise NutReadError("NUT вернул ошибку чтения UPS") from exc
    except OSError as exc:
        raise NutReadError(f"Не удалось запустить upsc: {exc}") from exc

    return parse_upsc_output(completed.stdout)


def _metric(value: object, policy: str) -> MetricValue:
    return MetricValue(value=value, policy=policy)


def ups_metrics(snapshot: UpsSnapshot) -> dict[str, MetricValue]:
    metrics: dict[str, MetricValue] = {
        "available": _metric(True, "discrete"),
        "status": _metric(snapshot.status_raw, "discrete"),
        "line_power": _metric(snapshot.line_power, "discrete"),
        "on_battery": _metric(snapshot.on_battery, "discrete"),
        "low_battery": _metric(snapshot.low_battery, "discrete"),
        "replace_battery": _metric(snapshot.replace_battery, "discrete"),
        "overload": _metric(snapshot.overload, "discrete"),
        "bypass": _metric(snapshot.bypass, "discrete"),
        "charging": _metric(snapshot.charging, "discrete"),
        "discharging": _metric(snapshot.discharging, "discrete"),
    }

    numeric = (
        ("battery_charge_percent", snapshot.battery_charge_percent, "ups_percent"),
        ("load_percent", snapshot.load_percent, "ups_percent"),
        ("runtime_seconds", snapshot.runtime_seconds, "ups_runtime_seconds"),
        ("battery_voltage_v", snapshot.battery_voltage_v, "ups_voltage"),
        ("input_voltage_v", snapshot.input_voltage_v, "ups_voltage"),
        ("output_voltage_v", snapshot.output_voltage_v, "ups_voltage"),
    )
    for key, value, policy in numeric:
        if value is not None:
            metrics[key] = _metric(value, policy)
    return metrics
