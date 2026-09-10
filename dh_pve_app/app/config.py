from __future__ import annotations

import configparser
import re
from dataclasses import dataclass
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
class AppConfig:
    general: GeneralConfig
    mqtt: MqttConfig


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
    )
