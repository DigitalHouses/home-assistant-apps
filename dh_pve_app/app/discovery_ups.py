from __future__ import annotations

from typing import Any

from .config import MqttConfig
from .identity import HostIdentity
from .topics import build_topics, build_ups_topics
from .ups_nut import UpsSnapshot


def _availability(topic: str) -> dict[str, str]:
    return {
        "topic": topic,
        "payload_available": "online",
        "payload_not_available": "offline",
    }


def _nut_availability(state_topic: str) -> dict[str, str]:
    return {
        "topic": state_topic,
        "value_template": "{{ 'online' if value_json.available | default(false) else 'offline' }}",
        "payload_available": "online",
        "payload_not_available": "offline",
    }


def build_ups_discovery_payload(
    config: MqttConfig,
    identity: HostIdentity,
    *,
    version: str,
    snapshot: UpsSnapshot | None,
) -> dict[str, Any]:
    pve_topics = build_topics(config, identity)
    topics = build_ups_topics(config, identity)

    def uid(component: str) -> str:
        return f"{topics.device_id}_{component}"

    app_availability = _availability(pve_topics.availability)
    telemetry_availability = [
        app_availability,
        _nut_availability(topics.state),
    ]

    components: dict[str, Any] = {
        "status": {
            "platform": "sensor",
            "name": "Status",
            "unique_id": uid("status"),
            "default_entity_id": "sensor.dh_ups_status",
            "state_topic": topics.state,
            "value_template": "{{ value_json.status | default('Unknown') }}",
            "availability": telemetry_availability,
            "availability_mode": "all",
            "icon": "mdi:power-plug-battery",
            "json_attributes_topic": topics.state,
            "json_attributes_template": (
                "{{ {'nut_status': value_json.status_raw | default(''), "
                "'status_tokens': value_json.status_tokens | default([])} | tojson }}"
            ),
        },
        "problems": {
            "platform": "sensor",
            "name": "Problems",
            "unique_id": uid("problems"),
            "default_entity_id": "sensor.dh_ups_problems",
            "state_topic": topics.state,
            "value_template": "{{ value_json.problems_count | default(0) }}",
            "availability": [app_availability],
            "availability_mode": "all",
            "icon": "mdi:alert-circle-check-outline",
            "json_attributes_topic": topics.state,
            "json_attributes_template": (
                "{{ {'severity': value_json.problems_severity | default('ok'), "
                "'details': value_json.problems_details | default(''), "
                "'problems': value_json.problems | default([])} | tojson }}"
            ),
        },
        "available": {
            "platform": "binary_sensor",
            "name": "NUT data available",
            "unique_id": uid("available"),
            "default_entity_id": "binary_sensor.dh_ups_available",
            "state_topic": topics.state,
            "value_template": "{{ 'ON' if value_json.available | default(false) else 'OFF' }}",
            "payload_on": "ON",
            "payload_off": "OFF",
            "availability": [app_availability],
            "availability_mode": "all",
            "entity_category": "diagnostic",
            "icon": "mdi:lan-connect",
        },
        "last_refresh": {
            "platform": "sensor",
            "name": "Last refresh",
            "unique_id": uid("last_refresh"),
            "default_entity_id": "sensor.dh_ups_last_refresh",
            "state_topic": topics.state,
            "value_template": "{{ value_json.last_refresh | default(none) }}",
            "availability": [app_availability],
            "availability_mode": "all",
            "entity_category": "diagnostic",
            "device_class": "timestamp",
            "icon": "mdi:refresh",
        },
        "refresh": {
            "platform": "button",
            "name": "Refresh",
            "unique_id": uid("refresh"),
            "default_entity_id": "button.dh_ups_refresh",
            "command_topic": topics.refresh,
            "payload_press": "PRESS",
            "availability": [app_availability],
            "availability_mode": "all",
            "entity_category": "diagnostic",
            "icon": "mdi:refresh",
        },
    }

    def add_sensor(
        key: str,
        name: str,
        entity_id: str,
        field: str,
        *,
        unit: str | None = None,
        device_class: str | None = None,
        entity_category: str | None = None,
        icon: str | None = None,
    ) -> None:
        component: dict[str, Any] = {
            "platform": "sensor",
            "name": name,
            "unique_id": uid(key),
            "default_entity_id": entity_id,
            "state_topic": topics.state,
            "value_template": f"{{{{ value_json.{field} }}}}",
            "availability": telemetry_availability,
            "availability_mode": "all",
        }
        if unit is not None:
            component["unit_of_measurement"] = unit
        if device_class is not None:
            component["device_class"] = device_class
        if entity_category is not None:
            component["entity_category"] = entity_category
        if icon is not None:
            component["icon"] = icon
        components[key] = component

    def add_binary(
        key: str,
        name: str,
        entity_id: str,
        field: str,
        icon: str,
        *,
        entity_category: str | None = None,
    ) -> None:
        component: dict[str, Any] = {
            "platform": "binary_sensor",
            "name": name,
            "unique_id": uid(key),
            "default_entity_id": entity_id,
            "state_topic": topics.state,
            "value_template": f"{{{{ 'ON' if value_json.{field} | default(false) else 'OFF' }}}}",
            "payload_on": "ON",
            "payload_off": "OFF",
            "availability": telemetry_availability,
            "availability_mode": "all",
            "icon": icon,
        }
        if entity_category is not None:
            component["entity_category"] = entity_category
        components[key] = component

    if snapshot is not None:
        if snapshot.battery_charge_percent is not None:
            add_sensor(
                "battery_charge", "Battery charge", "sensor.dh_ups_battery_charge",
                "battery_charge_percent", unit="%", device_class="battery",
            )
        if snapshot.runtime_seconds is not None:
            add_sensor(
                "battery_runtime", "Battery runtime", "sensor.dh_ups_battery_runtime",
                "runtime_seconds", unit="s", device_class="duration",
            )
        if snapshot.battery_voltage_v is not None:
            add_sensor(
                "battery_voltage", "Battery voltage", "sensor.dh_ups_battery_voltage",
                "battery_voltage_v", unit="V", device_class="voltage",
                entity_category="diagnostic",
            )
        if snapshot.load_percent is not None:
            add_sensor("load", "Load", "sensor.dh_ups_load", "load_percent", unit="%")
        if snapshot.nominal_real_power_w is not None:
            add_sensor(
                "nominal_real_power", "Nominal real power",
                "sensor.dh_ups_nominal_real_power", "nominal_real_power_w",
                unit="W", device_class="power", entity_category="diagnostic",
            )
        if snapshot.input_voltage_v is not None:
            add_sensor(
                "input_voltage", "Input voltage", "sensor.dh_ups_input_voltage",
                "input_voltage_v", unit="V", device_class="voltage",
            )
        if snapshot.output_voltage_v is not None:
            add_sensor(
                "output_voltage", "Output voltage", "sensor.dh_ups_output_voltage",
                "output_voltage_v", unit="V", device_class="voltage",
            )
        if snapshot.warning_charge_percent is not None:
            add_sensor(
                "battery_charge_warning", "Battery warning threshold",
                "sensor.dh_ups_battery_charge_warning", "warning_charge_percent",
                unit="%", entity_category="diagnostic",
            )
        if snapshot.low_charge_percent is not None:
            add_sensor(
                "battery_charge_low", "Battery low threshold",
                "sensor.dh_ups_battery_charge_low", "low_charge_percent",
                unit="%", entity_category="diagnostic",
            )
        if snapshot.low_runtime_seconds is not None:
            add_sensor(
                "battery_runtime_low", "Low runtime threshold",
                "sensor.dh_ups_battery_runtime_low", "low_runtime_seconds",
                unit="s", device_class="duration", entity_category="diagnostic",
            )
        if snapshot.test_result is not None:
            add_sensor(
                "test_result", "Last test result", "sensor.dh_ups_test_result",
                "test_result", entity_category="diagnostic", icon="mdi:clipboard-check-outline",
            )
        if snapshot.beeper_status is not None:
            add_sensor(
                "beeper_status", "Beeper status", "sensor.dh_ups_beeper_status",
                "beeper_status", entity_category="diagnostic", icon="mdi:volume-high",
            )

        if "ups.status" in snapshot.raw:
            add_binary(
                "on_battery", "On battery", "binary_sensor.dh_ups_on_battery",
                "on_battery", "mdi:battery-arrow-down",
            )
            add_binary(
                "low_battery", "Low battery", "binary_sensor.dh_ups_low_battery",
                "low_battery", "mdi:battery-alert",
            )
            add_binary(
                "replace_battery", "Replace battery", "binary_sensor.dh_ups_replace_battery",
                "replace_battery", "mdi:battery-sync-outline",
            )
            add_binary(
                "overload", "Overload", "binary_sensor.dh_ups_overload",
                "overload", "mdi:alert-octagon-outline",
            )
            add_binary(
                "bypass", "Bypass", "binary_sensor.dh_ups_bypass",
                "bypass", "mdi:transit-connection-variant",
            )
            add_binary(
                "charging", "Charging", "binary_sensor.dh_ups_charging",
                "charging", "mdi:battery-charging", entity_category="diagnostic",
            )
            add_binary(
                "discharging", "Discharging", "binary_sensor.dh_ups_discharging",
                "discharging", "mdi:battery-minus", entity_category="diagnostic",
            )

    device: dict[str, Any] = {
        "identifiers": [topics.device_id],
        "name": "DH UPS",
        "manufacturer": (snapshot.manufacturer if snapshot and snapshot.manufacturer else "DigitalHouses"),
        "model": (snapshot.model if snapshot and snapshot.model else "NUT UPS"),
        "sw_version": version,
    }
    if snapshot is not None and snapshot.serial:
        device["serial_number"] = snapshot.serial

    return {
        "device": device,
        "origin": {
            "name": "DigitalHouses DH PVE App",
            "sw_version": version,
            "support_url": (
                "https://github.com/DigitalHouses/home-assistant-apps/"
                "tree/main/dh_pve_app"
            ),
        },
        "components": components,
    }
