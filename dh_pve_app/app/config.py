from __future__ import annotations

import configparser
import re
from dataclasses import dataclass, field
from pathlib import Path

INSTANCE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_]*$")
LOG_LEVELS = {"debug", "info", "warning", "error"}
DEFAULT_TOPIC_PREFIX = "DigitalHouses/Global/dh_pve_app"
DEFAULT_DISCOVERY_PREFIX = "homeassistant"


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class GeneralConfig:
    instance_id: str
    node_name: str
    log_level: str


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
class UpsConfig:
    enabled: bool = False
    name: str = "ups"
    host: str = "127.0.0.1"
    port: int = 3493
    poll_interval_seconds: float = 5.0
    command_timeout_seconds: float = 3.0
    command_username: str = ""
    command_password: str = ""


@dataclass(frozen=True)
class AppConfig:
    general: GeneralConfig
    mqtt: MqttConfig
    ups: UpsConfig = field(default_factory=UpsConfig)


def _get(parser: configparser.ConfigParser, section: str, key: str, default: str) -> str:
    if not parser.has_section(section):
        return default
    return parser.get(section, key, fallback=default)


def _get_int(
    parser: configparser.ConfigParser,
    section: str,
    key: str,
    default: int,
) -> int:
    raw = _get(parser, section, key, str(default)).strip()
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{section}.{key} must be integer") from exc


def _get_float(
    parser: configparser.ConfigParser,
    section: str,
    key: str,
    default: float,
) -> float:
    raw = _get(parser, section, key, str(default)).strip()
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{section}.{key} must be numeric") from exc


def _get_bool(
    parser: configparser.ConfigParser,
    section: str,
    key: str,
    default: bool,
) -> bool:
    raw = _get(parser, section, key, "true" if default else "false").strip().lower()
    if raw == "true":
        return True
    if raw == "false":
        return False
    raise ConfigError(f"{section}.{key} must be true or false")


def load_config(path: Path) -> AppConfig:
    if not path.is_file():
        raise ConfigError(f"configuration file does not exist: {path}")

    parser = configparser.ConfigParser(interpolation=None)
    try:
        with path.open("r", encoding="utf-8") as handle:
            parser.read_file(handle)
    except (OSError, configparser.Error) as exc:
        raise ConfigError(f"unable to read configuration: {path}") from exc

    instance_id = _get(parser, "general", "instance_id", "").strip().lower()
    if instance_id and not INSTANCE_ID_RE.fullmatch(instance_id):
        raise ConfigError(
            "general.instance_id must match ^[a-z0-9][a-z0-9_]*$"
        )

    node_name = _get(parser, "general", "node_name", "PVE").strip() or "PVE"
    log_level = _get(parser, "general", "log_level", "info").strip().lower()
    if log_level not in LOG_LEVELS:
        raise ConfigError(
            f"general.log_level must be one of {sorted(LOG_LEVELS)}"
        )

    host = _get(parser, "mqtt", "host", "").strip()
    if not host:
        raise ConfigError("mqtt.host is required")

    port = _get_int(parser, "mqtt", "port", 1883)
    if not 1 <= port <= 65535:
        raise ConfigError("mqtt.port must be between 1 and 65535")

    username = _get(parser, "mqtt", "username", "")
    password = _get(parser, "mqtt", "password", "")
    topic_prefix = _get(
        parser, "mqtt", "topic_prefix", DEFAULT_TOPIC_PREFIX
    ).strip().rstrip("/")
    discovery_prefix = _get(
        parser, "mqtt", "discovery_prefix", DEFAULT_DISCOVERY_PREFIX
    ).strip().strip("/")
    keepalive_seconds = _get_int(parser, "mqtt", "keepalive_seconds", 60)

    if not topic_prefix:
        raise ConfigError("mqtt.topic_prefix must not be empty")
    if not discovery_prefix:
        raise ConfigError("mqtt.discovery_prefix must not be empty")
    if not 10 <= keepalive_seconds <= 3600:
        raise ConfigError("mqtt.keepalive_seconds must be between 10 and 3600")

    ups_enabled = _get_bool(parser, "ups", "enabled", False)
    ups_name = _get(parser, "ups", "name", "ups").strip()
    ups_host = _get(parser, "ups", "host", "127.0.0.1").strip()
    ups_port = _get_int(parser, "ups", "port", 3493)
    ups_poll_interval = _get_float(parser, "ups", "poll_interval_seconds", 5.0)
    ups_timeout = _get_float(parser, "ups", "command_timeout_seconds", 3.0)
    ups_command_username = _get(parser, "ups", "command_username", "").strip()
    ups_command_password = _get(parser, "ups", "command_password", "")

    if not ups_name:
        raise ConfigError("ups.name must not be empty")
    if not ups_host:
        raise ConfigError("ups.host must not be empty")
    if not 1 <= ups_port <= 65535:
        raise ConfigError("ups.port must be between 1 and 65535")
    if not 1.0 <= ups_poll_interval <= 300.0:
        raise ConfigError("ups.poll_interval_seconds must be between 1 and 300")
    if not 1.0 <= ups_timeout <= 30.0:
        raise ConfigError("ups.command_timeout_seconds must be between 1 and 30")

    return AppConfig(
        general=GeneralConfig(
            instance_id=instance_id,
            node_name=node_name,
            log_level=log_level,
        ),
        mqtt=MqttConfig(
            host=host,
            port=port,
            username=username,
            password=password,
            topic_prefix=topic_prefix,
            discovery_prefix=discovery_prefix,
            keepalive_seconds=keepalive_seconds,
        ),
        ups=UpsConfig(
            enabled=ups_enabled,
            name=ups_name,
            host=ups_host,
            port=ups_port,
            poll_interval_seconds=ups_poll_interval,
            command_timeout_seconds=ups_timeout,
            command_username=ups_command_username,
            command_password=ups_command_password,
        ),
    )
