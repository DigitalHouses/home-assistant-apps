from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from threading import RLock
from typing import Mapping

SETTINGS_FILE = Path("/data/runtime_settings.json")

DISK_USAGE_THRESHOLD_KEY = "disk_usage_threshold_percent"
DISK_USAGE_THRESHOLD_DEFAULT = 80.0
DISK_USAGE_THRESHOLD_MIN = 1.0
DISK_USAGE_THRESHOLD_MAX = 98.0
DISK_USAGE_THRESHOLD_STEP = 1.0


# Migration inputs retain their original names. The persisted values become
# authoritative once initialized, even if old Supervisor options still exist.
RUNTIME_SETTINGS = {
    "publish_interval_minutes": (1, 60, 1, "Publish interval", "min"),
    "recorder_stale_seconds": (30, 86400, 300, "Recorder stale threshold", "s"),
    "top_entities_limit": (1, 100, 10, "Top entities count", None),
}
_LOCK = RLock()


class RuntimeSettingError(ValueError):
    pass


def _validate_disk_usage_threshold(value: object) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeSettingError("disk usage threshold must be numeric") from exc
    if not (DISK_USAGE_THRESHOLD_MIN <= parsed <= DISK_USAGE_THRESHOLD_MAX):
        raise RuntimeSettingError(
            f"disk usage threshold must be between "
            f"{DISK_USAGE_THRESHOLD_MIN:g} and {DISK_USAGE_THRESHOLD_MAX:g}"
        )
    stepped = round(parsed / DISK_USAGE_THRESHOLD_STEP) * DISK_USAGE_THRESHOLD_STEP
    if abs(stepped - parsed) > 1e-9:
        raise RuntimeSettingError(
            f"disk usage threshold must use step {DISK_USAGE_THRESHOLD_STEP:g}"
        )
    return float(parsed)


def _read(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeSettingError("runtime settings file is invalid") from exc
    if not isinstance(payload, dict):
        raise RuntimeSettingError("runtime settings file must contain an object")
    if DISK_USAGE_THRESHOLD_KEY not in payload:
        raise RuntimeSettingError(f"runtime settings file is missing {DISK_USAGE_THRESHOLD_KEY}")
    return payload


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)


def load_disk_usage_threshold(path: Path = SETTINGS_FILE) -> float:
    with _LOCK:
        return _validate_disk_usage_threshold(_read(path).get(
            DISK_USAGE_THRESHOLD_KEY, DISK_USAGE_THRESHOLD_DEFAULT))


def save_disk_usage_threshold(value: object, path: Path = SETTINGS_FILE) -> float:
    validated = _validate_disk_usage_threshold(value)
    with _LOCK:
        payload = _read(path)
        payload[DISK_USAGE_THRESHOLD_KEY] = validated
        _write(path, payload)
    return validated


def validate_runtime_setting(key: str, value: object) -> int:
    low, high, _, _, _ = RUNTIME_SETTINGS[key]
    try:
        parsed = float(value)
        if isinstance(value, bool) or not low <= parsed <= high or not parsed.is_integer():
            raise ValueError
        return int(parsed)
    except (TypeError, ValueError, OverflowError) as exc:
        raise RuntimeSettingError(f"{key} must be an integer between {low} and {high}") from exc


def migrate_runtime_settings(legacy: Mapping[str, object], path: Path = SETTINGS_FILE) -> dict[str, int]:
    with _LOCK:
        payload = _read(path)
        original = dict(payload)
        payload[DISK_USAGE_THRESHOLD_KEY] = _validate_disk_usage_threshold(
            payload.get(DISK_USAGE_THRESHOLD_KEY, DISK_USAGE_THRESHOLD_DEFAULT))
        settings = {}
        for key, (_, _, default, _, _) in RUNTIME_SETTINGS.items():
            settings[key] = validate_runtime_setting(key, payload.get(key, legacy.get(key, default)))
        payload.update(settings)
        if original != payload:
            _write(path, payload)
        return settings


def save_runtime_setting(key: str, value: object, path: Path = SETTINGS_FILE) -> int:
    validated = validate_runtime_setting(key, value)
    with _LOCK:
        payload = _read(path)
        payload.setdefault(DISK_USAGE_THRESHOLD_KEY, DISK_USAGE_THRESHOLD_DEFAULT)
        payload[key] = validated
        _write(path, payload)
    return validated


if __name__ == "__main__":
    # Save old values before removing the deprecated Supervisor options.
    options = json.loads(Path("/data/options.json").read_text(encoding="utf-8"))
    migrate_runtime_settings(options)
