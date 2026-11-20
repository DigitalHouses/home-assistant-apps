"""Single native INI configuration for DigitalHouses PBS Agent."""
from __future__ import annotations

import configparser
import re
from dataclasses import dataclass
from pathlib import Path

PRODUCT_ID = "digitalhouses_pbs_agent"
REPO = "https://github.com/DigitalHouses/home-assistant-apps"
DEFAULT_CONFIG = Path("/etc/digitalhouses_pbs_agent/digitalhouses_pbs_agent.conf")
KEYS = {
    "instance_id": ("general", "instance_id"),
    "log_level": ("general", "log_level"),
    "mqtt_host": ("mqtt", "host"),
    "mqtt_port": ("mqtt", "port"),
    "mqtt_username": ("mqtt", "username"),
    "mqtt_password": ("mqtt", "password"),
    "mqtt_keepalive_seconds": ("mqtt", "keepalive_seconds"),
    "pbs_datastores": ("pbs", "datastores"),
    "monitor_poll_seconds": ("monitor", "poll_seconds"),
    "monitor_backup_rules": ("monitor", "backup_rules"),
    "monitor_sync_rules": ("monitor", "sync_rules"),
    "monitor_warning_percent": ("monitor", "warning_percent"),
    "monitor_critical_percent": ("monitor", "critical_percent"),
}
KEYS.update({f"{s}.{k}": (s, k) for s, k in KEYS.values()})
KEYS["mqtt_ip"] = KEYS["mqtt_host"]
SECRETS = {("mqtt", "password")}


@dataclass(frozen=True)
class BackupRule:
    datastore: str
    namespace: str
    group: str
    max_age_hours: float


@dataclass(frozen=True)
class SyncRule:
    job_id: str
    max_age_hours: float


@dataclass(frozen=True)
class Config:
    instance_id: str
    log_level: str
    mqtt_host: str
    mqtt_port: int
    mqtt_username: str
    mqtt_password: str
    mqtt_keepalive_seconds: int
    datastores: tuple[str, ...]
    poll_seconds: int
    backup_rules: tuple[BackupRule, ...]
    sync_rules: tuple[SyncRule, ...]
    warning_percent: float
    critical_percent: float


def _csv(s: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in s.split(",") if item.strip())


def _parse_rules(value: str, parts: int, label: str) -> tuple[tuple[str, ...], ...]:
    if not value.strip():
        return ()
    rules = []
    for raw in value.split(";"):
        tokens = tuple(part.strip() for part in raw.split("|"))
        if len(tokens) != parts or not all(tokens):
            raise ValueError(f"{label}: invalid rule")
        rules.append(tokens)
    return tuple(rules)


def load_config(path: Path = DEFAULT_CONFIG) -> Config:
    parser = configparser.ConfigParser(interpolation=None)
    if not path.is_file():
        raise ValueError("native INI is missing")
    with path.open(encoding="utf-8") as stream:
        parser.read_file(stream)
    def get(section: str, key: str, default: str = "") -> str:
        return parser.get(section, key, fallback=default).strip()
    def integer(section: str, key: str, default: str, low: int, high: int) -> int:
        value = int(get(section, key, default))
        if not low <= value <= high:
            raise ValueError(f"{section}.{key}: invalid range")
        return value
    def percentage(key: str, default: str) -> float:
        value = float(get("monitor", key, default))
        if not 0 <= value <= 100:
            raise ValueError(f"monitor.{key}: must be 0..100")
        return value

    instance = get("general", "instance_id", "")
    if instance and not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", instance):
        raise ValueError("general.instance_id: invalid")
    level = get("general", "log_level", "info").lower()
    if level not in {"debug", "info", "warning", "error"}:
        raise ValueError("general.log_level: invalid")
    host = get("mqtt", "host")
    if not host:
        raise ValueError("mqtt.host is required")
    stores = _csv(get("pbs", "datastores"))
    if not stores or len(stores) != len(set(stores)) or not all(re.fullmatch(r"[a-zA-Z0-9_-]+", s) for s in stores):
        raise ValueError("pbs.datastores: expected unique datastore names")
    backup = tuple(
        BackupRule(store, ns if ns != "-" else "", group, float(hours))
        for store, ns, group, hours in _parse_rules(
            get("monitor", "backup_rules"), 4, "monitor.backup_rules"
        )
    )
    for item in backup:
        if item.datastore not in stores or item.max_age_hours <= 0 or item.max_age_hours > 8760:
            raise ValueError("monitor.backup_rules: invalid datastore or age")
        if not re.fullmatch(r"(vm|ct|host)/[^/]+", item.group):
            raise ValueError("monitor.backup_rules: group must be vm/ID, ct/ID or host/ID")
    sync = tuple(
        SyncRule(job, float(hours))
        for job, hours in _parse_rules(get("monitor", "sync_rules"), 2, "monitor.sync_rules")
    )
    if any(x.max_age_hours <= 0 or x.max_age_hours > 8760 for x in sync):
        raise ValueError("monitor.sync_rules: age must be positive")
    warning = percentage("warning_percent", "80")
    critical = percentage("critical_percent", "90")
    if warning >= critical:
        raise ValueError("warning_percent must be less than critical_percent")
    return Config(
        instance_id=instance, log_level=level,
        mqtt_host=host, mqtt_port=integer("mqtt", "port", "1883", 1, 65535),
        mqtt_username=get("mqtt", "username"), mqtt_password=get("mqtt", "password"),
        mqtt_keepalive_seconds=integer("mqtt", "keepalive_seconds", "60", 10, 3600),
        datastores=stores,
        poll_seconds=integer("monitor", "poll_seconds", "300", 60, 3600),
        backup_rules=backup, sync_rules=sync,
        warning_percent=warning, critical_percent=critical,
    )
