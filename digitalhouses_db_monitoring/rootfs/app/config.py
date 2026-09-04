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
class AppConfig:
    database: DatabaseConfig
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
        connection = str(raw.get('connection', 'supervisor')).lower()
        if connection == 'supervisor':
            db = DatabaseConfig(
                engine='mariadb',
                host=_required(os.getenv('MYSQL_SERVICE_HOST'), 'Supervisor MySQL service host'),
                port=_bounded_int(os.getenv('MYSQL_SERVICE_PORT'), 1, 65535, 3306),
                database=_required(raw.get('database', 'homeassistant'), 'MariaDB database'),
                username=_required(os.getenv('MYSQL_SERVICE_USER'), 'Supervisor MySQL service username'),
                password=_required(os.getenv('MYSQL_SERVICE_PASSWORD'), 'Supervisor MySQL service password'),
            )
        elif connection == 'manual':
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

    log_level = str(options.get('log_level', 'info')).lower()
    if log_level not in {'debug', 'info', 'warning', 'error'}:
        log_level = 'info'

    timezone_name = str(os.getenv('TZ') or options.get('timezone') or 'UTC').strip() or 'UTC'

    return AppConfig(
        database=db,
        publish_interval_minutes=_bounded_int(
            options.get('publish_interval_minutes'), 1, 60, 1
        ),
        recorder_stale_seconds=_bounded_int(options.get('recorder_stale_seconds'), 30, 86400, 300),
        log_level=log_level,
        timezone=timezone_name,
    )
