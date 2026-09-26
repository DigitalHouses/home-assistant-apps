from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

SETTINGS_FILE = Path("/data/runtime_settings.json")

DISK_USAGE_THRESHOLD_KEY = "disk_usage_threshold_percent"
DISK_USAGE_THRESHOLD_DEFAULT = 80.0
DISK_USAGE_THRESHOLD_MIN = 1.0
DISK_USAGE_THRESHOLD_MAX = 98.0
DISK_USAGE_THRESHOLD_STEP = 1.0


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


def load_disk_usage_threshold(path: Path = SETTINGS_FILE) -> float:
    if not path.exists():
        return DISK_USAGE_THRESHOLD_DEFAULT

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeSettingError("runtime settings file is invalid") from exc
    if not isinstance(payload, dict):
        raise RuntimeSettingError("runtime settings file must contain an object")
    if DISK_USAGE_THRESHOLD_KEY not in payload:
        raise RuntimeSettingError(
            f"runtime settings file is missing {DISK_USAGE_THRESHOLD_KEY}"
        )
    return _validate_disk_usage_threshold(payload[DISK_USAGE_THRESHOLD_KEY])


def save_disk_usage_threshold(
    value: object,
    path: Path = SETTINGS_FILE,
) -> float:
    validated = _validate_disk_usage_threshold(value)
    payload = {
        DISK_USAGE_THRESHOLD_KEY: validated,
    }
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
    return validated
