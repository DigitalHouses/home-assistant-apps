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
    recovery: RecoveryConfig
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

    recovery_raw = raw.get("recovery")
    if not isinstance(recovery_raw, dict):
        recovery_raw = {}

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
