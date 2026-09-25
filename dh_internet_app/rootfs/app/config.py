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


def _bounded_int(value: Any, minimum: int, maximum: int, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _target(raw: Any, name: str) -> RecoveryTarget:
    if not isinstance(raw, dict):
        raw = {}
    action = str(raw.get("action", "switch")).strip().lower()
    if action not in {"button", "switch"}:
        raise ConfigError(f"recovery.{name}.action must be button or switch")
    entity_id = str(raw.get("entity_id", "")).strip()
    prefix = f"{action}."
    if entity_id and not entity_id.startswith(prefix):
        raise ConfigError(
            f"recovery.{name}.entity_id must start with {prefix!r} for action {action}"
        )
    return RecoveryTarget(
        action=action,
        entity_id=entity_id,
        power_off_seconds=_bounded_int(
            raw.get("power_off_seconds"), 1, 120, 10
        ),
    )


def parse_options(raw: Any) -> AppConfig:
    if not isinstance(raw, dict):
        raise ConfigError("options must be a JSON object")

    router_ip = str(raw.get("router_ip", "")).strip()
    try:
        ipaddress.ip_address(router_ip)
    except ValueError as exc:
        raise ConfigError("router_ip must be a valid IPv4 or IPv6 address") from exc

    connectivity_raw = raw.get("connectivity_check")
    if not isinstance(connectivity_raw, dict):
        connectivity_raw = {}

    speedtest_raw = raw.get("speedtest")
    if not isinstance(speedtest_raw, dict):
        speedtest_raw = {}

    server_ids_raw = speedtest_raw.get("server_ids", [])
    if not isinstance(server_ids_raw, list):
        raise ConfigError("speedtest.server_ids must be a list")
    server_ids: list[int] = []
    for raw_server_id in server_ids_raw:
        try:
            server_id = int(raw_server_id)
        except (TypeError, ValueError) as exc:
            raise ConfigError("speedtest.server_ids must contain integers") from exc
        if server_id <= 0:
            raise ConfigError("speedtest.server_ids must contain positive integers")
        if server_id not in server_ids:
            server_ids.append(server_id)

    traffic_raw = raw.get("traffic")
    if not isinstance(traffic_raw, dict):
        traffic_raw = {}

    recovery_raw = raw.get("recovery")
    if not isinstance(recovery_raw, dict):
        recovery_raw = {}

    traffic_download_total = str(
        traffic_raw.get("traffic_download_total", "")
    ).strip()
    traffic_upload_total = str(
        traffic_raw.get("traffic_upload_total", "")
    ).strip()
    router_wan_status = str(traffic_raw.get("router_wan_status", "")).strip()
    router_download_rate = str(
        traffic_raw.get("router_download_rate", "")
    ).strip()
    router_upload_rate = str(
        traffic_raw.get("router_upload_rate", "")
    ).strip()

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

    enabled = bool(recovery_raw.get("enabled", False))
    mode = str(recovery_raw.get("mode", "smart")).strip().lower()
    if mode not in {"smart", "both"}:
        raise ConfigError("recovery.mode must be smart or both")

    ont = _target(recovery_raw.get("ont"), "ont")
    router = _target(recovery_raw.get("router"), "router")
    if enabled:
        if not ont.entity_id:
            raise ConfigError("recovery.ont.entity_id is required when recovery is enabled")
        if not router.entity_id:
            raise ConfigError(
                "recovery.router.entity_id is required when recovery is enabled"
            )

    level = str(raw.get("log_level", "info")).strip().lower()
    if level not in {"debug", "info", "warning", "error"}:
        level = "info"

    return AppConfig(
        router_ip=router_ip,
        connectivity=ConnectivityConfig(
            interval_seconds=_bounded_int(
                connectivity_raw.get("interval_seconds"), 5, 3600, 10
            ),
            attempts=_bounded_int(connectivity_raw.get("attempts"), 1, 10, 3),
            timeout_seconds=_bounded_int(
                connectivity_raw.get("timeout_seconds"), 1, 30, 2
            ),
        ),
        speedtest=SpeedtestConfig(
            periodic_enabled=bool(speedtest_raw.get("periodic_enabled", True)),
            interval_seconds=60
            * _bounded_int(speedtest_raw.get("interval_minutes"), 5, 720, 30),
            timeout_seconds=_bounded_int(
                speedtest_raw.get("timeout_seconds"), 30, 600, 240
            ),
            server_ids=tuple(server_ids),
            automatic_server_fallback=bool(
                speedtest_raw.get("automatic_server_fallback", True)
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
            max_cycles=_bounded_int(recovery_raw.get("max_cycles"), 1, 10, 3),
            retry_interval_seconds=60
            * _bounded_int(recovery_raw.get("retry_interval_minutes"), 1, 60, 5),
            boot_wait_seconds=60
            * _bounded_int(recovery_raw.get("boot_wait_minutes"), 1, 30, 3),
            cooldown_seconds=60
            * _bounded_int(recovery_raw.get("cooldown_minutes"), 1, 1440, 15),
            ont=ont,
            router=router,
        ),
        telemetry_enabled=bool(raw.get("telemetry_enabled", False)),
        log_level=level,
    )


def load_config(path: Path = OPTIONS_FILE) -> AppConfig:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"options file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"invalid JSON in {path}: {exc}") from exc
    return parse_options(raw)
