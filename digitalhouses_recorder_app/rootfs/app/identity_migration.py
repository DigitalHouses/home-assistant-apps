from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATE_FILE = Path("/data/ha_mqtt_identity_migration.json")
SCHEMA_VERSION = 1
PHASE_BRIDGE = "bridge"
PHASE_COMPLETED = "completed"

LEGACY_BASE_TOPIC = "DigitalHouses/Global/db_monitoring"
LEGACY_DEVICE_ID = "digitalhouses_db_monitoring"
CANONICAL_BASE_TOPIC = (
    "DigitalHouses/Global/digitalhouses_recorder_app"
)
CANONICAL_DEVICE_ID = "digitalhouses_recorder_app"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_state(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8")
        )
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "Unable to read HA/MQTT identity migration state"
        ) from exc
    if not isinstance(value, dict):
        raise RuntimeError(
            "HA/MQTT identity migration state must be an object"
        )
    return value


def _write_state(
    state: dict[str, Any],
    path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(
            state,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    tmp.replace(path)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def ensure_bridge_state(
    release_version: str,
    path: Path = STATE_FILE,
) -> bool:
    """Persist bridge state and return whether legacy mirroring is allowed.

    Once a later cleanup release marks the migration completed, rolling back
    to this bridge release must not resurrect the legacy HA/MQTT identity.
    """

    state = _read_state(path)
    if (
        state.get("schema_version") == SCHEMA_VERSION
        and state.get("phase") == PHASE_COMPLETED
    ):
        return False

    bridge_state = {
        "schema_version": SCHEMA_VERSION,
        "phase": PHASE_BRIDGE,
        "release_version": release_version,
        "legacy_base_topic": LEGACY_BASE_TOPIC,
        "legacy_device_id": LEGACY_DEVICE_ID,
        "canonical_base_topic": CANONICAL_BASE_TOPIC,
        "canonical_device_id": CANONICAL_DEVICE_ID,
        "cleanup_pending": True,
        "updated_at": _utc_now(),
    }

    if (
        state.get("schema_version") == SCHEMA_VERSION
        and state.get("phase") == PHASE_BRIDGE
        and state.get("release_version") == release_version
        and state.get("legacy_base_topic")
        == LEGACY_BASE_TOPIC
        and state.get("legacy_device_id")
        == LEGACY_DEVICE_ID
        and state.get("canonical_base_topic")
        == CANONICAL_BASE_TOPIC
        and state.get("canonical_device_id")
        == CANONICAL_DEVICE_ID
        and state.get("cleanup_pending") is True
    ):
        return True

    _write_state(bridge_state, path)
    return True



def cleanup_required(
    path: Path = STATE_FILE,
) -> bool:
    """Return whether retained legacy HA/MQTT identity cleanup is pending."""

    state = _read_state(path)
    return not (
        state.get("schema_version") == SCHEMA_VERSION
        and state.get("phase") == PHASE_COMPLETED
        and state.get("cleanup_pending") is False
    )


def mark_cleanup_complete(
    release_version: str,
    path: Path = STATE_FILE,
) -> None:
    """Reserved for the cleanup release after live bridge acceptance."""

    _write_state(
        {
            "schema_version": SCHEMA_VERSION,
            "phase": PHASE_COMPLETED,
            "release_version": release_version,
            "legacy_base_topic": LEGACY_BASE_TOPIC,
            "legacy_device_id": LEGACY_DEVICE_ID,
            "canonical_base_topic": CANONICAL_BASE_TOPIC,
            "canonical_device_id": CANONICAL_DEVICE_ID,
            "cleanup_pending": False,
            "updated_at": _utc_now(),
        },
        path,
    )
