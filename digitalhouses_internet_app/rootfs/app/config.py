"""Configuration parsing for DigitalHouses Internet App."""

from __future__ import annotations

import ipaddress
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

OPTIONS_FILE = Path("/data/options.json")


class ConfigError(ValueError):
    """Raised when the App configuration is invalid."""


@dataclass(frozen=True)
class ConnectivityConfig:
    interval_seconds: int
    attempts: int
    timeout_seconds: int


@dataclass(frozen=True)
class SpeedtestConfig:
    periodic_enabled: bool
    interval_seconds: int
    timeout_seconds: int
    server_ids: tuple[int, ...]
    automatic_server_fallback: bool


@dataclass(frozen=True)
class TrafficConfig:
    traffic_download_total: str
    traffic_upload_total: str
    router_wan_status: str
    router_download_rate: str
    router_upload_rate: str

    @property
    def enabled(self) -> bool:
        return bool(self.traffic_download_total and self.traffic_upload_total)

    @property
    def configured(self) -> bool:
        return self.enabled

    @property
    def has_bindings(self) -> bool:
        return any(
            (
                self.traffic_download_total,
                self.traffic_upload_total,
                self.router_wan_status,
                self.router_download_rate,
                self.router_upload_rate,
            )
        )


@dataclass(frozen=True)
class RecoveryTarget:
    action: str
    entity_id: str
    power_off_seconds: int


@dataclass(frozen=True)
class RecoveryConfig:
    enabled: bool
    mode: str
    max_cycles: int
    retry_interval_seconds: int
    boot_wait_seconds: int
    cooldown_seconds: int
    ont: RecoveryTarget
    router: RecoveryTarget


@dataclass(frozen=True)
class AppConfig:
    router_ip: str
    connectivity: ConnectivityConfig
    speedtest: SpeedtestConfig
    traffic: TrafficConfig
    recovery: RecoveryConfig
    telemetry_enabled: bool
    log_level: str


def _mapping_option(raw: dict[str, Any], key: str) -> dict[str, Any]:
    if key not in raw:
        return {}
    value = raw[key]
    if not isinstance(value, dict):
        raise ConfigError(f"{key} must be an object")
    return value


def _int_option(
    raw: dict[str, Any],
    key: str,
    *,
    minimum: int,
    maximum: int,
    default: int,
    prefix: str,
) -> int:
    if key not in raw:
        return default
    value = raw[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{prefix}.{key} must be an integer")
    if not minimum <= value <= maximum:
        raise ConfigError(
            f"{prefix}.{key} must be between {minimum} and {maximum}"
        )
    return value


def _bool_option(
    raw: dict[str, Any],
    key: str,
    *,
    default: bool,
    prefix: str,
) -> bool:
    if key not in raw:
        return default
    value = raw[key]
    if not isinstance(value, bool):
        raise ConfigError(f"{prefix}.{key} must be boolean")
    return value


def _string_option(
    raw: dict[str, Any],
    key: str,
    *,
    default: str,
    prefix: str,
) -> str:
    if key not in raw:
        return default
    value = raw[key]
    if not isinstance(value, str):
        raise ConfigError(f"{prefix}.{key} must be a string")
    return value.strip()


def _target(raw: dict[str, Any], name: str) -> RecoveryTarget:
    prefix = f"recovery.{name}"
    action = _string_option(
        raw,
        "action",
        default="switch",
        prefix=prefix,
    ).lower()
    if action not in {"button", "switch"}:
        raise ConfigError(f"{prefix}.action must be button or switch")

    entity_id = _string_option(
        raw,
        "entity_id",
        default="",
        prefix=prefix,
    )
    domain = f"{action}."
    if entity_id and not entity_id.startswith(domain):
        raise ConfigError(
            f"{prefix}.entity_id must start with {domain!r} for action {action}"
        )

    return RecoveryTarget(
        action=action,
        entity_id=entity_id,
        power_off_seconds=_int_option(
            raw,
            "power_off_seconds",
            minimum=1,
            maximum=120,
            default=10,
            prefix=prefix,
        ),
    )


def parse_options(raw: Any) -> AppConfig:
    if not isinstance(raw, dict):
        raise ConfigError("options must be a JSON object")

    router_ip = _string_option(
        raw,
        "router_ip",
        default="192.168.1.1",
        prefix="options",
    )
    try:
        ipaddress.ip_address(router_ip)
    except ValueError as exc:
        raise ConfigError("router_ip must be a valid IPv4 or IPv6 address") from exc

    connectivity_raw = _mapping_option(raw, "connectivity_check")
    speedtest_raw = _mapping_option(raw, "speedtest")
    traffic_raw = _mapping_option(raw, "traffic")
    recovery_raw = _mapping_option(raw, "recovery")

    server_ids_raw = speedtest_raw.get("server_ids", [])
    if not isinstance(server_ids_raw, list):
        raise ConfigError("speedtest.server_ids must be a list")
    server_ids: list[int] = []
    for raw_server_id in server_ids_raw:
        if isinstance(raw_server_id, bool) or not isinstance(raw_server_id, int):
            raise ConfigError("speedtest.server_ids must contain integers")
        if raw_server_id <= 0:
            raise ConfigError("speedtest.server_ids must contain positive integers")
        if raw_server_id not in server_ids:
            server_ids.append(raw_server_id)

    traffic_download_total = _string_option(
        traffic_raw,
        "traffic_download_total",
        default="",
        prefix="traffic",
    )
    traffic_upload_total = _string_option(
        traffic_raw,
        "traffic_upload_total",
        default="",
        prefix="traffic",
    )
    router_wan_status = _string_option(
        traffic_raw,
        "router_wan_status",
        default="",
        prefix="traffic",
    )
    router_download_rate = _string_option(
        traffic_raw,
        "router_download_rate",
        default="",
        prefix="traffic",
    )
    router_upload_rate = _string_option(
        traffic_raw,
        "router_upload_rate",
        default="",
        prefix="traffic",
    )

    if bool(traffic_download_total) != bool(traffic_upload_total):
        raise ConfigError(
            "traffic download/upload total entity IDs must be configured together"
        )
    for name, entity_id in (
        ("traffic_download_total", traffic_download_total),
        ("traffic_upload_total", traffic_upload_total),
        ("router_download_rate", router_download_rate),
        ("router_upload_rate", router_upload_rate),
    ):
        if entity_id and not entity_id.startswith("sensor."):
            raise ConfigError(f"traffic.{name} must be a sensor.* entity")
    if router_wan_status and not router_wan_status.startswith(
        ("sensor.", "binary_sensor.")
    ):
        raise ConfigError(
            "traffic.router_wan_status must be sensor.* or binary_sensor.*"
        )

    enabled = _bool_option(
        recovery_raw,
        "enabled",
        default=False,
        prefix="recovery",
    )
    mode = _string_option(
        recovery_raw,
        "mode",
        default="smart",
        prefix="recovery",
    ).lower()
    if mode not in {"smart", "both"}:
        raise ConfigError("recovery.mode must be smart or both")

    ont_raw = _mapping_option(recovery_raw, "ont")
    router_raw = _mapping_option(recovery_raw, "router")
    ont = _target(ont_raw, "ont")
    router = _target(router_raw, "router")
    if enabled:
        if not ont.entity_id:
            raise ConfigError(
                "recovery.ont.entity_id is required when recovery is enabled"
            )
        if not router.entity_id:
            raise ConfigError(
                "recovery.router.entity_id is required when recovery is enabled"
            )

    level = _string_option(
        raw,
        "log_level",
        default="info",
        prefix="options",
    ).lower()
    if level not in {"debug", "info", "warning", "error"}:
        raise ConfigError(
            "log_level must be debug, info, warning or error"
        )

    return AppConfig(
        router_ip=router_ip,
        connectivity=ConnectivityConfig(
            interval_seconds=_int_option(
                connectivity_raw,
                "interval_seconds",
                minimum=5,
                maximum=3600,
                default=10,
                prefix="connectivity_check",
            ),
            attempts=_int_option(
                connectivity_raw,
                "attempts",
                minimum=1,
                maximum=10,
                default=3,
                prefix="connectivity_check",
            ),
            timeout_seconds=_int_option(
                connectivity_raw,
                "timeout_seconds",
                minimum=1,
                maximum=30,
                default=2,
                prefix="connectivity_check",
            ),
        ),
        speedtest=SpeedtestConfig(
            periodic_enabled=_bool_option(
                speedtest_raw,
                "periodic_enabled",
                default=True,
                prefix="speedtest",
            ),
            interval_seconds=60
            * _int_option(
                speedtest_raw,
                "interval_minutes",
                minimum=5,
                maximum=720,
                default=30,
                prefix="speedtest",
            ),
            timeout_seconds=_int_option(
                speedtest_raw,
                "timeout_seconds",
                minimum=30,
                maximum=600,
                default=240,
                prefix="speedtest",
            ),
            server_ids=tuple(server_ids),
            automatic_server_fallback=_bool_option(
                speedtest_raw,
                "automatic_server_fallback",
                default=True,
                prefix="speedtest",
            ),
        ),
        traffic=TrafficConfig(
            traffic_download_total=traffic_download_total,
            traffic_upload_total=traffic_upload_total,
            router_wan_status=router_wan_status,
            router_download_rate=router_download_rate,
            router_upload_rate=router_upload_rate,
        ),
        recovery=RecoveryConfig(
            enabled=enabled,
            mode=mode,
            max_cycles=_int_option(
                recovery_raw,
                "max_cycles",
                minimum=1,
                maximum=10,
                default=3,
                prefix="recovery",
            ),
            retry_interval_seconds=60
            * _int_option(
                recovery_raw,
                "retry_interval_minutes",
                minimum=1,
                maximum=60,
                default=5,
                prefix="recovery",
            ),
            boot_wait_seconds=60
            * _int_option(
                recovery_raw,
                "boot_wait_minutes",
                minimum=1,
                maximum=30,
                default=3,
                prefix="recovery",
            ),
            cooldown_seconds=60
            * _int_option(
                recovery_raw,
                "cooldown_minutes",
                minimum=1,
                maximum=1440,
                default=15,
                prefix="recovery",
            ),
            ont=ont,
            router=router,
        ),
        telemetry_enabled=_bool_option(
            raw,
            "telemetry_enabled",
            default=False,
            prefix="options",
        ),
        log_level=level,
    )


def load_config(path: Path = OPTIONS_FILE) -> AppConfig:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"options file not found: {path}") from exc
    except OSError as exc:
        raise ConfigError(f"unable to read options file {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"invalid JSON in {path}: {exc}") from exc
    return parse_options(raw)
