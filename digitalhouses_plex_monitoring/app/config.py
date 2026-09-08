from __future__ import annotations

import configparser
import re
from dataclasses import dataclass
from pathlib import Path

INSTANCE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_]*$")
LOG_LEVELS = {"debug", "info", "warning", "error"}


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class GeneralConfig:
    instance_id: str
    instance_name: str
    poll_interval_seconds: float
    cpu_window_seconds: float
    log_level: str


@dataclass(frozen=True)
class TelemetryConfig:
    cpu_change_threshold: float
    high_load_threshold: float
    high_load_publish_interval_seconds: float


@dataclass(frozen=True)
class MqttConfig:
    host: str
    port: int
    username: str
    password: str
    topic_prefix: str
    discovery_prefix: str
    keepalive_seconds: int


@dataclass(frozen=True)
class AppConfig:
    general: GeneralConfig
    telemetry: TelemetryConfig
    mqtt: MqttConfig


def entity_prefix(instance_id: str) -> str:
    return f"dh_{instance_id}"


def _get_float(
    parser: configparser.ConfigParser,
    section: str,
    key: str,
    default: float,
) -> float:
    raw = parser.get(section, key, fallback=str(default)).strip()
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{section}.{key} must be numeric, got {raw!r}") from exc


def _get_int(
    parser: configparser.ConfigParser,
    section: str,
    key: str,
    default: int,
) -> int:
    raw = parser.get(section, key, fallback=str(default)).strip()
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{section}.{key} must be integer, got {raw!r}") from exc


def load_config(path: Path) -> AppConfig:
    if not path.is_file():
        raise ConfigError(f"configuration file does not exist: {path}")

    parser = configparser.ConfigParser(interpolation=None)
    try:
        with path.open("r", encoding="utf-8") as handle:
            parser.read_file(handle)
    except (OSError, configparser.Error) as exc:
        raise ConfigError(f"unable to read configuration {path}: {exc}") from exc

    instance_id = parser.get("general", "instance_id", fallback="plex").strip()
    if not INSTANCE_ID_RE.fullmatch(instance_id):
        raise ConfigError(
            "general.instance_id must match ^[a-z0-9][a-z0-9_]*$"
        )

    instance_name = parser.get(
        "general", "instance_name", fallback="DH Plex"
    ).strip() or "DH Plex"
    poll = _get_float(parser, "general", "poll_interval_seconds", 10.0)
    cpu_window = _get_float(parser, "general", "cpu_window_seconds", 60.0)
    log_level = parser.get("general", "log_level", fallback="info").strip().lower()

    if not 2.0 <= poll <= 300.0:
        raise ConfigError("general.poll_interval_seconds must be between 2 and 300")
    if cpu_window < poll:
        raise ConfigError("general.cpu_window_seconds must be >= poll interval")
    if cpu_window > 3600.0:
        raise ConfigError("general.cpu_window_seconds must be <= 3600")
    if log_level not in LOG_LEVELS:
        raise ConfigError(
            f"general.log_level must be one of {sorted(LOG_LEVELS)}, got {log_level!r}"
        )

    cpu_change = _get_float(parser, "telemetry", "cpu_change_threshold", 5.0)
    high_load = _get_float(parser, "telemetry", "high_load_threshold", 80.0)
    high_interval = _get_float(
        parser,
        "telemetry",
        "high_load_publish_interval_seconds",
        60.0,
    )
    if cpu_change <= 0:
        raise ConfigError("telemetry.cpu_change_threshold must be > 0")
    if high_load <= 0:
        raise ConfigError("telemetry.high_load_threshold must be > 0")
    if high_interval < poll:
        raise ConfigError(
            "telemetry.high_load_publish_interval_seconds must be >= poll interval"
        )

    host = parser.get("mqtt", "host", fallback="").strip()
    if not host:
        raise ConfigError("mqtt.host is required")
    port = _get_int(parser, "mqtt", "port", 1883)
    if not 1 <= port <= 65535:
        raise ConfigError("mqtt.port must be between 1 and 65535")

    username = parser.get("mqtt", "username", fallback="")
    password = parser.get("mqtt", "password", fallback="")
    topic_prefix = parser.get(
        "mqtt",
        "topic_prefix",
        fallback="DigitalHouses/Global/plex_monitoring",
    ).strip().rstrip("/")
    discovery_prefix = parser.get(
        "mqtt", "discovery_prefix", fallback="homeassistant"
    ).strip().strip("/")
    keepalive = _get_int(parser, "mqtt", "keepalive_seconds", 60)
    if not topic_prefix:
        raise ConfigError("mqtt.topic_prefix must not be empty")
    if not discovery_prefix:
        raise ConfigError("mqtt.discovery_prefix must not be empty")
    if not 10 <= keepalive <= 3600:
        raise ConfigError("mqtt.keepalive_seconds must be between 10 and 3600")

    return AppConfig(
        general=GeneralConfig(
            instance_id=instance_id,
            instance_name=instance_name,
            poll_interval_seconds=poll,
            cpu_window_seconds=cpu_window,
            log_level=log_level,
        ),
        telemetry=TelemetryConfig(
            cpu_change_threshold=cpu_change,
            high_load_threshold=high_load,
            high_load_publish_interval_seconds=high_interval,
        ),
        mqtt=MqttConfig(
            host=host,
            port=port,
            username=username,
            password=password,
            topic_prefix=topic_prefix,
            discovery_prefix=discovery_prefix,
            keepalive_seconds=keepalive,
        ),
    )
