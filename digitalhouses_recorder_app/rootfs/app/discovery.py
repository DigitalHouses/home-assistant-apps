from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from contracts import (
    EVENT_SCHEMA_VERSION,
    validate_release_version,
)

PRODUCT_ID = "digitalhouses_recorder_app"
ENTITY_PREFIX = "dh_recorder_app"
DEVICE_NAME = "DH Recorder"

LEGACY_DEVICE_ID = "digitalhouses_db_monitoring"
LEGACY_ENTITY_PREFIX = "dh_db"
LEGACY_BASE_TOPIC = "DigitalHouses/Global/db_monitoring"

DEVICE_ID = PRODUCT_ID
BASE_TOPIC = f"DigitalHouses/Global/{PRODUCT_ID}"

HA_STATUS_TOPIC = "homeassistant/status"
STATE_RETAIN = True


@dataclass(frozen=True)
class DiscoveryIdentity:
    device_id: str
    entity_prefix: str
    base_topic: str
    canonical: bool

    @property
    def state_topic(self) -> str:
        return f"{self.base_topic}/state"

    @property
    def top_entities_24h_topic(self) -> str:
        return f"{self.base_topic}/top_entities_24h"

    @property
    def top_entities_all_time_topic(self) -> str:
        return f"{self.base_topic}/top_entities_all_time"

    @property
    def app_availability_topic(self) -> str:
        return f"{self.base_topic}/availability"

    @property
    def db_availability_topic(self) -> str:
        return f"{self.base_topic}/database_availability"

    @property
    def db_status_availability_topic(self) -> str:
        return f"{self.base_topic}/database_status_availability"

    @property
    def db_static_availability_topic(self) -> str:
        return f"{self.base_topic}/database_static_availability"

    @property
    def storage_availability_topic(self) -> str:
        return f"{self.base_topic}/storage_availability"

    @property
    def discovery_topic(self) -> str:
        return f"homeassistant/device/{self.device_id}/config"

    @property
    def refresh_command_topic(self) -> str:
        return f"{self.base_topic}/refresh"

    @property
    def event_topic(self) -> str:
        return f"{self.base_topic}/event/diagnostic"

    @property
    def disk_usage_threshold_state_topic(self) -> str:
        return (
            f"{self.base_topic}/settings/"
            "disk_usage_threshold_percent/state"
        )

    @property
    def disk_usage_threshold_command_topic(self) -> str:
        return (
            f"{self.base_topic}/settings/"
            "disk_usage_threshold_percent/set"
        )

    @property
    def telemetry_delete_command_topic(self) -> str:
        return f"{self.base_topic}/telemetry/delete"

    def entity_id(self, domain: str, unique_suffix: str) -> str:
        if self.canonical:
            suffix = {
                "app_version": "version",
                "app_started_at": "started_at",
                "diagnostic_event": "diagnostic",
            }.get(unique_suffix, unique_suffix)
        else:
            if unique_suffix == "diagnostic_event":
                suffix = "diagnostic"
            elif unique_suffix.startswith("db_"):
                suffix = unique_suffix[3:]
            else:
                suffix = unique_suffix
        return f"{domain}.{self.entity_prefix}_{suffix}"


CANONICAL_IDENTITY = DiscoveryIdentity(
    device_id=DEVICE_ID,
    entity_prefix=ENTITY_PREFIX,
    base_topic=BASE_TOPIC,
    canonical=True,
)
LEGACY_IDENTITY = DiscoveryIdentity(
    device_id=LEGACY_DEVICE_ID,
    entity_prefix=LEGACY_ENTITY_PREFIX,
    base_topic=LEGACY_BASE_TOPIC,
    canonical=False,
)

STATE_TOPIC = CANONICAL_IDENTITY.state_topic
TOP_ENTITIES_24H_TOPIC = (
    CANONICAL_IDENTITY.top_entities_24h_topic
)
TOP_ENTITIES_ALL_TIME_TOPIC = (
    CANONICAL_IDENTITY.top_entities_all_time_topic
)
APP_AVAILABILITY_TOPIC = (
    CANONICAL_IDENTITY.app_availability_topic
)
DB_AVAILABILITY_TOPIC = (
    CANONICAL_IDENTITY.db_availability_topic
)
DB_STATUS_AVAILABILITY_TOPIC = (
    CANONICAL_IDENTITY.db_status_availability_topic
)
DB_STATIC_AVAILABILITY_TOPIC = (
    CANONICAL_IDENTITY.db_static_availability_topic
)
STORAGE_AVAILABILITY_TOPIC = (
    CANONICAL_IDENTITY.storage_availability_topic
)
DISCOVERY_TOPIC = CANONICAL_IDENTITY.discovery_topic
REFRESH_COMMAND_TOPIC = (
    CANONICAL_IDENTITY.refresh_command_topic
)
EVENT_TOPIC = CANONICAL_IDENTITY.event_topic
DISK_USAGE_THRESHOLD_STATE_TOPIC = (
    CANONICAL_IDENTITY.disk_usage_threshold_state_topic
)
DISK_USAGE_THRESHOLD_COMMAND_TOPIC = (
    CANONICAL_IDENTITY.disk_usage_threshold_command_topic
)
TELEMETRY_DELETE_COMMAND_TOPIC = (
    CANONICAL_IDENTITY.telemetry_delete_command_topic
)

LEGACY_STATE_TOPIC = LEGACY_IDENTITY.state_topic
LEGACY_TOP_ENTITIES_24H_TOPIC = (
    LEGACY_IDENTITY.top_entities_24h_topic
)
LEGACY_TOP_ENTITIES_ALL_TIME_TOPIC = (
    LEGACY_IDENTITY.top_entities_all_time_topic
)
LEGACY_APP_AVAILABILITY_TOPIC = (
    LEGACY_IDENTITY.app_availability_topic
)
LEGACY_DB_AVAILABILITY_TOPIC = (
    LEGACY_IDENTITY.db_availability_topic
)
LEGACY_DB_STATUS_AVAILABILITY_TOPIC = (
    LEGACY_IDENTITY.db_status_availability_topic
)
LEGACY_DB_STATIC_AVAILABILITY_TOPIC = (
    LEGACY_IDENTITY.db_static_availability_topic
)
LEGACY_STORAGE_AVAILABILITY_TOPIC = (
    LEGACY_IDENTITY.storage_availability_topic
)
LEGACY_DISCOVERY_TOPIC = LEGACY_IDENTITY.discovery_topic
LEGACY_REFRESH_COMMAND_TOPIC = (
    LEGACY_IDENTITY.refresh_command_topic
)
LEGACY_EVENT_TOPIC = LEGACY_IDENTITY.event_topic
LEGACY_DISK_USAGE_THRESHOLD_STATE_TOPIC = (
    LEGACY_IDENTITY.disk_usage_threshold_state_topic
)
LEGACY_DISK_USAGE_THRESHOLD_COMMAND_TOPIC = (
    LEGACY_IDENTITY.disk_usage_threshold_command_topic
)


def _availability(topic: str) -> dict[str, str]:
    return {
        "topic": topic,
        "payload_available": "online",
        "payload_not_available": "offline",
    }


def _availability_list(
    identity: DiscoveryIdentity,
    *,
    db_required: bool,
    db_status_required: bool,
    db_static_required: bool,
    storage_required: bool,
) -> list[dict[str, str]]:
    # The canonical App availability topic is the LWT guard for both
    # canonical and temporary legacy bridge entities. This prevents the
    # legacy mirror from appearing online after an abrupt container stop.
    result = [_availability(APP_AVAILABILITY_TOPIC)]
    if db_required:
        result.append(
            _availability(identity.db_availability_topic)
        )
    if db_status_required:
        result.append(
            _availability(
                identity.db_status_availability_topic
            )
        )
    if db_static_required:
        result.append(
            _availability(
                identity.db_static_availability_topic
            )
        )
    if storage_required:
        result.append(
            _availability(
                identity.storage_availability_topic
            )
        )
    return result


def _component(
    identity: DiscoveryIdentity,
    platform: str,
    name: str,
    suffix: str,
    value_template: str,
    *,
    diagnostic: bool = False,
    db_required: bool = True,
    db_status_required: bool = False,
    db_static_required: bool = False,
    storage_required: bool = False,
    state_topic: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "platform": platform,
        "name": name,
        "unique_id": f"{identity.device_id}_{suffix}",
        "default_entity_id": identity.entity_id(
            platform,
            suffix,
        ),
        "state_topic": (
            identity.state_topic
            if state_topic is None
            else state_topic
        ),
        "value_template": value_template,
        "availability": _availability_list(
            identity,
            db_required=db_required,
            db_status_required=db_status_required,
            db_static_required=db_static_required,
            storage_required=storage_required,
        ),
        "availability_mode": "all",
    }
    if diagnostic:
        payload["entity_category"] = "diagnostic"
    payload.update(extra)
    return payload


def _button_component(
    identity: DiscoveryIdentity,
    name: str,
    suffix: str,
    command_topic: str,
    *,
    diagnostic: bool = False,
    entity_category: str | None = None,
    payload_press: str = "PRESS",
    icon: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "platform": "button",
        "name": name,
        "unique_id": f"{identity.device_id}_{suffix}",
        "default_entity_id": identity.entity_id(
            "button",
            suffix,
        ),
        "command_topic": command_topic,
        "payload_press": payload_press,
        "availability": _availability_list(
            identity,
            db_required=False,
            db_status_required=False,
            db_static_required=False,
            storage_required=False,
        ),
        "availability_mode": "all",
    }
    if diagnostic:
        payload["entity_category"] = "diagnostic"
    if entity_category:
        payload["entity_category"] = entity_category
    if icon:
        payload["icon"] = icon
    return payload


def _number_component(
    identity: DiscoveryIdentity,
    name: str,
    suffix: str,
    state_topic: str,
    command_topic: str,
    *,
    minimum: float,
    maximum: float,
    step: float,
    unit: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "platform": "number",
        "name": name,
        "unique_id": f"{identity.device_id}_{suffix}",
        "default_entity_id": identity.entity_id(
            "number",
            suffix,
        ),
        "state_topic": state_topic,
        "command_topic": command_topic,
        "min": minimum,
        "max": maximum,
        "step": step,
        "mode": "box",
        "entity_category": "config",
        "availability": _availability_list(
            identity,
            db_required=False,
            db_status_required=False,
            db_static_required=False,
            storage_required=False,
        ),
        "availability_mode": "all",
    }
    if unit:
        payload["unit_of_measurement"] = unit
    return payload


def _event_component(
    identity: DiscoveryIdentity,
    event_types: list[str],
) -> dict[str, Any]:
    return {
        "platform": "event",
        "name": "Diagnostic event",
        "unique_id": (
            f"{identity.device_id}_diagnostic_event"
        ),
        "default_entity_id": identity.entity_id(
            "event",
            "diagnostic_event",
        ),
        "state_topic": identity.event_topic,
        "event_types": event_types,
        "availability": _availability_list(
            identity,
            db_required=False,
            db_status_required=False,
            db_static_required=False,
            storage_required=False,
        ),
        "availability_mode": "all",
    }


def _build_components(
    identity: DiscoveryIdentity,
    *,
    include_storage: bool,
    include_canonical_runtime: bool,
) -> dict[str, dict[str, Any]]:
    components: dict[str, dict[str, Any]] = {
        "db_start": _component(
            identity,
            "sensor",
            "DB start",
            "db_start",
            "{{ value_json.db_start }}",
            diagnostic=True,
            device_class="timestamp",
            icon="mdi:database-clock-outline",
        ),
        "db_last": _component(
            identity,
            "sensor",
            "DB last record",
            "db_last",
            "{{ value_json.db_last }}",
            diagnostic=True,
            device_class="timestamp",
            icon="mdi:database-clock",
        ),
        "db_last_refresh": _component(
            identity,
            "sensor",
            "DB last refresh",
            "db_last_refresh",
            "{{ value_json.db_last_refresh }}",
            diagnostic=True,
            db_required=False,
            device_class="timestamp",
            icon="mdi:database-sync",
        ),
        "db_depth": _component(
            identity,
            "sensor",
            "DB history depth",
            "db_depth",
            "{{ value_json.db_depth }}",
            diagnostic=True,
            device_class="duration",
            state_class="measurement",
            unit_of_measurement="d",
            icon="mdi:calendar-range",
        ),
        "db_records_per_hour": _component(
            identity,
            "sensor",
            "DB records per hour",
            "db_records_per_hour",
            "{{ value_json.db_records_per_hour }}",
            diagnostic=True,
            state_class="measurement",
            unit_of_measurement="k rec/h",
            icon="mdi:database-arrow-down",
        ),
        "db_records": _component(
            identity,
            "sensor",
            "DB records",
            "db_records",
            "{{ value_json.db_records }}",
            diagnostic=True,
            state_class="measurement",
            unit_of_measurement="k records",
            icon="mdi:database-marker",
        ),
        "db_size": _component(
            identity,
            "sensor",
            "DB size",
            "db_size",
            "{{ value_json.db_size }}",
            diagnostic=True,
            device_class="data_size",
            state_class="measurement",
            unit_of_measurement="MiB",
            suggested_display_precision=1,
            icon="mdi:database",
        ),
        "db_version": _component(
            identity,
            "sensor",
            "DB version",
            "db_version",
            "{{ value_json.db_version }}",
            diagnostic=True,
            db_required=False,
            db_static_required=True,
            icon="mdi:database-cog",
        ),
        "db_yesterday_records": _component(
            identity,
            "sensor",
            "DB inserted yesterday",
            "db_yesterday_records",
            "{{ value_json.db_yesterday_records }}",
            diagnostic=True,
            state_class="measurement",
            unit_of_measurement="records",
            icon="mdi:calendar-arrow-left",
        ),
        "db_name": _component(
            identity,
            "sensor",
            "DB name",
            "db_name",
            "{{ value_json.db_name }}",
            diagnostic=True,
            db_required=False,
            db_static_required=True,
            icon="mdi:database-settings",
        ),
        "db_user": _component(
            identity,
            "sensor",
            "DB user",
            "db_user",
            "{{ value_json.db_user }}",
            diagnostic=True,
            db_required=False,
            db_static_required=True,
            icon="mdi:account-key",
        ),
        "db_connected": _component(
            identity,
            "binary_sensor",
            "DB connected",
            "db_connected",
            (
                "{{ 'ON' if value_json.db_connected "
                "else 'OFF' }}"
            ),
            diagnostic=True,
            db_required=False,
            db_status_required=True,
            device_class="connectivity",
        ),
        "recorder_writing": _component(
            identity,
            "binary_sensor",
            "DB recorder writing",
            "recorder_writing",
            (
                "{{ 'ON' if value_json.recorder_writing "
                "else 'OFF' }}"
            ),
            diagnostic=True,
            icon="mdi:database-edit",
        ),
        "db_last_age": _component(
            identity,
            "sensor",
            "DB last age",
            "db_last_age",
            "{{ value_json.db_last_age }}",
            diagnostic=True,
            device_class="duration",
            state_class="measurement",
            unit_of_measurement="s",
            icon="mdi:timer-sand",
        ),
        "db_top_entities_24h": _component(
            identity,
            "sensor",
            "DB top entities 24h",
            "db_top_entities_24h",
            "{{ value_json.top_records }}",
            diagnostic=True,
            state_topic=identity.top_entities_24h_topic,
            state_class="measurement",
            unit_of_measurement="records",
            icon="mdi:format-list-numbered",
            json_attributes_topic=(
                identity.top_entities_24h_topic
            ),
            json_attributes_template=(
                "{{ value_json | tojson }}"
            ),
        ),
        "db_top_entities_all_time": _component(
            identity,
            "sensor",
            "DB top entities all time",
            "db_top_entities_all_time",
            "{{ value_json.top_records }}",
            diagnostic=True,
            state_topic=(
                identity.top_entities_all_time_topic
            ),
            state_class="measurement",
            unit_of_measurement="records",
            icon="mdi:format-list-numbered",
            json_attributes_topic=(
                identity.top_entities_all_time_topic
            ),
            json_attributes_template=(
                "{{ value_json | tojson }}"
            ),
        ),
        "db_refresh": _button_component(
            identity,
            "DB refresh",
            "db_refresh",
            identity.refresh_command_topic,
            diagnostic=True,
            icon="mdi:refresh",
        ),
        "db_disk_usage_threshold": _number_component(
            identity,
            "DB disk usage threshold",
            "db_disk_usage_threshold",
            identity.disk_usage_threshold_state_topic,
            identity.disk_usage_threshold_command_topic,
            minimum=1,
            maximum=98,
            step=1,
            unit="%",
        ),
        "diagnostic_event": _event_component(
            identity,
            [
                "db_connection_lost",
                "db_connection_restored",
                "recorder_writing_stopped",
                "recorder_writing_restored",
                "storage_usage_high",
                "storage_usage_normal",
            ],
        ),
    }

    if include_canonical_runtime:
        components.update(
            {
                "database_type": _component(
                    identity,
                    "sensor",
                    "Database type",
                    "database_type",
                    "{{ value_json.db_type }}",
                    diagnostic=True,
                    db_required=False,
                    icon="mdi:database-outline",
                ),
                "app_version": _component(
                    identity,
                    "sensor",
                    "Version",
                    "app_version",
                    "{{ value_json.version }}",
                    diagnostic=True,
                    db_required=False,
                    icon="mdi:tag-outline",
                ),
                "app_started_at": _component(
                    identity,
                    "sensor",
                    "Started at",
                    "app_started_at",
                    "{{ value_json.started_at }}",
                    diagnostic=True,
                    db_required=False,
                    device_class="timestamp",
                    icon="mdi:clock-start",
                ),
                "delete_telemetry": _button_component(
                    identity,
                    "Delete telemetry data",
                    "delete_telemetry",
                    identity.telemetry_delete_command_topic,
                    entity_category="config",
                    icon="mdi:database-remove-outline",
                ),
            }
        )

    if include_storage:
        for key, name, suffix, state_key in (
            (
                "db_disk_free",
                "DB disk free",
                "db_disk_free",
                "db_disk_free",
            ),
            (
                "db_disk_used",
                "DB disk used",
                "db_disk_used",
                "db_disk_used",
            ),
            (
                "db_disk_total",
                "DB disk total",
                "db_disk_total",
                "db_disk_total",
            ),
        ):
            components[key] = _component(
                identity,
                "sensor",
                name,
                suffix,
                f"{{{{ value_json.{state_key} }}}}",
                diagnostic=True,
                db_required=False,
                storage_required=True,
                device_class="data_size",
                state_class="measurement",
                unit_of_measurement="GB",
                suggested_display_precision=1,
                icon="mdi:harddisk",
            )
        components[
            "db_disk_used_percentage"
        ] = _component(
            identity,
            "sensor",
            "DB disk used",
            "db_disk_used_percentage",
            "{{ value_json.db_disk_used_percentage }}",
            diagnostic=True,
            db_required=False,
            storage_required=True,
            state_class="measurement",
            unit_of_measurement="%",
            suggested_display_precision=1,
            icon="mdi:harddisk",
        )

    return components


def _build_payload(
    identity: DiscoveryIdentity,
    app_version: str,
    *,
    include_storage: bool,
    include_canonical_runtime: bool,
) -> dict[str, Any]:
    version = validate_release_version(app_version)
    return {
        "device": {
            "identifiers": [identity.device_id],
            "name": DEVICE_NAME,
            "manufacturer": "DigitalHouses",
            "model": (
                "Home Assistant Recorder Database Monitor"
            ),
            "sw_version": version,
        },
        "origin": {
            "name": "DigitalHouses Recorder App",
            "sw_version": version,
            "support_url": (
                "https://github.com/DigitalHouses/"
                "home-assistant-apps/tree/main/"
                "digitalhouses_recorder_app"
            ),
        },
        "components": _build_components(
            identity,
            include_storage=include_storage,
            include_canonical_runtime=(
                include_canonical_runtime
            ),
        ),
    }


def build_discovery_payload(
    app_version: str,
    include_storage: bool = False,
) -> dict[str, Any]:
    return _build_payload(
        CANONICAL_IDENTITY,
        app_version,
        include_storage=include_storage,
        include_canonical_runtime=True,
    )


def build_legacy_discovery_payload(
    app_version: str,
    include_storage: bool = False,
) -> dict[str, Any]:
    return _build_payload(
        LEGACY_IDENTITY,
        app_version,
        include_storage=include_storage,
        include_canonical_runtime=False,
    )
