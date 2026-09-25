from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

OPTIONS_FILE = Path('/data/options.json')


@dataclass(frozen=True)
class DatabaseConfig:
    engine: str
    host: str
    port: int
    database: str
    username: str
    password: str


@dataclass(frozen=True)
class StorageConfig:
    source: str
    host: str
    port: int
    username: str
    password: str
    path: str


@dataclass(frozen=True)
class AppConfig:
    database: DatabaseConfig
    storage: StorageConfig
    publish_interval_minutes: int
    recorder_stale_seconds: int
    log_level: str
    timezone: str


def _read_options(path: Path = OPTIONS_FILE) -> dict[str, Any]:
    with path.open('r', encoding='utf-8') as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError('App options must be a JSON object')
    return data


def _bounded_int(value: Any, minimum: int, maximum: int, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _required(value: Any, label: str) -> str:
    text = str(value or '').strip()
    if not text:
        raise ValueError(f'{label} is required')
    return text


def load_config(path: Path = OPTIONS_FILE) -> AppConfig:
    options = _read_options(path)
    engine = str(options.get('database_type', 'postgresql')).lower()
    mariadb_connection = ''

    if engine == 'postgresql':
        raw = options.get('postgresql') or {}
        if not isinstance(raw, dict):
            raw = {}
        db = DatabaseConfig(
            engine='postgresql',
            host=_required(raw.get('host'), 'PostgreSQL host'),
            port=_bounded_int(raw.get('port'), 1, 65535, 5432),
            database=_required(raw.get('database'), 'PostgreSQL database'),
            username=_required(raw.get('username'), 'PostgreSQL username'),
            password=_required(raw.get('password'), 'PostgreSQL password'),
        )
    elif engine == 'mariadb':
        raw = options.get('mariadb') or {}
        if not isinstance(raw, dict):
            raw = {}
        mariadb_connection = str(raw.get('connection', 'supervisor')).lower()
        if mariadb_connection == 'supervisor':
            db = DatabaseConfig(
                engine='mariadb',
                host=_required(os.getenv('MYSQL_SERVICE_HOST'), 'Supervisor MySQL service host'),
                port=_bounded_int(os.getenv('MYSQL_SERVICE_PORT'), 1, 65535, 3306),
                database=_required(raw.get('database', 'homeassistant'), 'MariaDB database'),
                username=_required(os.getenv('MYSQL_SERVICE_USER'), 'Supervisor MySQL service username'),
                password=_required(os.getenv('MYSQL_SERVICE_PASSWORD'), 'Supervisor MySQL service password'),
            )
        elif mariadb_connection == 'manual':
            db = DatabaseConfig(
                engine='mariadb',
                host=_required(raw.get('host'), 'MariaDB host'),
                port=_bounded_int(raw.get('port'), 1, 65535, 3306),
                database=_required(raw.get('database'), 'MariaDB database'),
                username=_required(raw.get('username'), 'MariaDB username'),
                password=_required(raw.get('password'), 'MariaDB password'),
            )
        else:
            raise ValueError("MariaDB connection must be 'supervisor' or 'manual'")
    else:
        raise ValueError("database_type must be 'postgresql' or 'mariadb'")

    storage_raw = options.get('storage') or {}
    if not isinstance(storage_raw, dict):
        storage_raw = {}
    requested_storage = str(storage_raw.get('source', 'automatic')).lower()
    if requested_storage not in {'automatic', 'ssh', 'disabled'}:
        raise ValueError("Storage source must be 'automatic', 'ssh' or 'disabled'")

    ssh_host = str(storage_raw.get('ssh_host') or '').strip() or db.host
    ssh_port = _bounded_int(storage_raw.get('ssh_port'), 1, 65535, 22)
    ssh_username = str(storage_raw.get('ssh_username') or '').strip()
    ssh_password = str(storage_raw.get('ssh_password') or '')
    storage_path = str(storage_raw.get('path') or '').strip()

    if requested_storage == 'disabled':
        storage_source = 'disabled'
    elif requested_storage == 'automatic' and engine == 'mariadb' and mariadb_connection == 'supervisor':
        storage_source = 'supervisor'
    elif requested_storage == 'automatic':
        storage_source = 'ssh' if ssh_username and ssh_password else 'disabled'
    else:
        storage_source = 'ssh'
        ssh_username = _required(ssh_username, 'Storage SSH username')
        ssh_password = _required(ssh_password, 'Storage SSH password')

    storage = StorageConfig(
        source=storage_source,
        host=ssh_host,
        port=ssh_port,
        username=ssh_username,
        password=ssh_password,
        path=storage_path,
    )

    log_level = str(options.get('log_level', 'info')).lower()
    if log_level not in {'debug', 'info', 'warning', 'error'}:
        log_level = 'info'

    timezone_name = str(os.getenv('TZ') or options.get('timezone') or 'UTC').strip() or 'UTC'

    return AppConfig(
        database=db,
        storage=storage,
        publish_interval_minutes=_bounded_int(
            options.get('publish_interval_minutes'), 1, 60, 1
        ),
        recorder_stale_seconds=_bounded_int(options.get('recorder_stale_seconds'), 30, 86400, 300),
        log_level=log_level,
        timezone=timezone_name,
    )
