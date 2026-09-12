from __future__ import annotations

from typing import Any

from .config import MqttConfig
from .identity import HostIdentity
from .topics import build_topics, build_ups_topics
from .ups_control import UpsCapabilities
from .ups_nut import UpsSnapshot
from .ups_shutdown_policy import UpsShutdownPolicy


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
    capabilities: UpsCapabilities | None = None,
    shutdown_policy: UpsShutdownPolicy | None = None,
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
            "default_entity_id": "sensor.dh_pve_ups_status",
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
            "default_entity_id": "sensor.dh_pve_ups_problems",
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
            "default_entity_id": "binary_sensor.dh_pve_ups_available",
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
            "default_entity_id": "sensor.dh_pve_ups_last_refresh",
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
            "default_entity_id": "button.dh_pve_ups_refresh",
            "command_topic": topics.refresh,
            "payload_press": "PRESS",
            "availability": [app_availability],
            "availability_mode": "all",
            "entity_category": "diagnostic",
            "icon": "mdi:refresh",
        },
        "capabilities": {
            "platform": "sensor",
            "name": "Capabilities",
            "unique_id": uid("capabilities"),
            "default_entity_id": "sensor.dh_pve_ups_capabilities",
            "state_topic": topics.state,
            "value_template": (
                "{{ (value_json.capabilities.count | default(0) | string) ~ ' commands' "
                "if value_json.capabilities.available | default(false) else 'Unavailable' }}"
            ),
            "availability": [app_availability],
            "availability_mode": "all",
            "entity_category": "diagnostic",
            "icon": "mdi:application-cog-outline",
            "json_attributes_topic": topics.state,
            "json_attributes_template": (
                "{{ {'commands': value_json.capabilities.commands | default([]), "
                "'battery_tests': value_json.capabilities.battery_tests | default([]), "
                "'beeper_control': value_json.capabilities.beeper_control | default(false), "
                "'load_control': value_json.capabilities.load_control | default(false), "
                "'shutdown_control': value_json.capabilities.shutdown_control | default(false), "
                "'supported_features': value_json.capabilities.supported_features | default([])} | tojson }}"
            ),
        },
        "shutdown_policy": {
            "platform": "sensor",
            "name": "Shutdown policy",
            "unique_id": uid("shutdown_policy"),
            "default_entity_id": "sensor.dh_pve_ups_shutdown_policy",
            "state_topic": topics.state,
            "value_template": "{{ value_json.shutdown_policy.state | default('Unknown') }}",
            "availability": [app_availability],
            "availability_mode": "all",
            "entity_category": "diagnostic",
            "icon": "mdi:power-settings",
            "json_attributes_topic": topics.state,
            "json_attributes_template": (
                "{{ {'role': value_json.shutdown_policy.role | default('unknown'), "
                "'nut_monitor': value_json.shutdown_policy.nut_monitor | default('unknown'), "
                "'shutdown_enabled': value_json.shutdown_policy.shutdown_enabled | default(false), "
                "'shutdown_command': value_json.shutdown_policy.shutdown_command | default(none), "
                "'min_supplies': value_json.shutdown_policy.min_supplies | default(none), "
                "'pollfreq_seconds': value_json.shutdown_policy.pollfreq_seconds | default(none), "
                "'pollfreqalert_seconds': value_json.shutdown_policy.pollfreqalert_seconds | default(none), "
                "'deadtime_seconds': value_json.shutdown_policy.deadtime_seconds | default(none), "
                "'hostsync_seconds': value_json.shutdown_policy.hostsync_seconds | default(none), "
                "'finaldelay_seconds': value_json.shutdown_policy.finaldelay_seconds | default(none), "
                "'upssched_present': value_json.shutdown_policy.upssched_present | default(false), "
                "'upssched_rules': value_json.shutdown_policy.upssched_rules | default(0), "
                "'upssched_active': value_json.shutdown_policy.upssched_active | default(false), "
                "'guest_shutdown_budget_seconds': value_json.shutdown_policy.guest_shutdown_budget_seconds | default(none), "
                "'power_restore_behavior': value_json.shutdown_policy.power_restore_behavior | default('Not configured')} | tojson }}"
            ),
        },
        "policy_on_battery_delay": {
            "platform": "number",
            "name": "Shutdown wait after power loss",
            "unique_id": uid("policy_on_battery_delay"),
            "default_entity_id": "number.dh_pve_ups_policy_on_battery_delay",
            "state_topic": topics.state,
            "value_template": "{{ value_json.policy.draft.on_battery_delay_minutes | default(30) }}",
            "command_topic": topics.policy_on_battery_delay_set,
            "min": 5,
            "max": 60,
            "step": 5,
            "unit_of_measurement": "min",
            "mode": "slider",
            "availability": [app_availability],
            "availability_mode": "all",
            "icon": "mdi:timer-outline",
        },
        "policy_power_restore_delay": {
            "platform": "number",
            "name": "Power restore delay",
            "unique_id": uid("policy_power_restore_delay"),
            "default_entity_id": "number.dh_pve_ups_policy_power_restore_delay",
            "state_topic": topics.state,
            "value_template": "{{ value_json.policy.draft.power_restore_delay_seconds | default(120) }}",
            "command_topic": topics.policy_power_restore_delay_set,
            "min": 60,
            "max": 300,
            "step": 30,
            "unit_of_measurement": "s",
            "mode": "slider",
            "availability": [app_availability],
            "availability_mode": "all",
            "icon": "mdi:power-cycle",
        },
        "policy_apply": {
            "platform": "button",
            "name": "Apply policy",
            "unique_id": uid("policy_apply"),
            "default_entity_id": "button.dh_pve_ups_apply_policy",
            "command_topic": topics.policy_apply,
            "payload_press": "PRESS",
            "availability": [app_availability],
            "availability_mode": "all",
            "icon": "mdi:check-decagram-outline",
        },
        "policy_status": {
            "platform": "sensor",
            "name": "Policy status",
            "unique_id": uid("policy_status"),
            "default_entity_id": "sensor.dh_pve_ups_policy_status",
            "state_topic": topics.state,
            "value_template": "{{ value_json.policy.status | default('Commissioning') }}",
            "availability": [app_availability],
            "availability_mode": "all",
            "icon": "mdi:shield-check-outline",
        },
        "policy_apply_result": {
            "platform": "sensor",
            "name": "Policy apply result",
            "unique_id": uid("policy_apply_result"),
            "default_entity_id": "sensor.dh_pve_ups_policy_apply_result",
            "state_topic": topics.state,
            "value_template": "{{ value_json.policy.apply_result | default('Not applied') }}",
            "availability": [app_availability],
            "availability_mode": "all",
            "icon": "mdi:clipboard-check-outline",
        },
        "policy_last_applied": {
            "platform": "sensor",
            "name": "Policy last applied",
            "unique_id": uid("policy_last_applied"),
            "default_entity_id": "sensor.dh_pve_ups_policy_last_applied",
            "state_topic": topics.state,
            "value_template": "{{ value_json.policy.last_applied | default(none) }}",
            "device_class": "timestamp",
            "availability": [app_availability],
            "availability_mode": "all",
            "icon": "mdi:calendar-check-outline",
            "json_attributes_topic": topics.state,
            "json_attributes_template": (
                "{{ {'policy_revision': value_json.policy.policy_revision | default(0), "
                "'policy_hash': value_json.policy.policy_hash | default(none)} | tojson }}"
            ),
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

    def add_button(key: str, name: str, entity_id: str, command_topic: str, icon: str) -> None:
        components[key] = {
            "platform": "button",
            "name": name,
            "unique_id": uid(key),
            "default_entity_id": entity_id,
            "command_topic": command_topic,
            "payload_press": "PRESS",
            "availability": telemetry_availability,
            "availability_mode": "all",
            "icon": icon,
        }

    if capabilities is not None:
        if capabilities.supports_test("quick"):
            add_button(
                "test_quick", "Quick battery test", "button.dh_pve_ups_test_quick",
                topics.test_quick, "mdi:battery-sync",
            )
        if capabilities.supports_test("deep"):
            add_button(
                "test_deep", "Deep battery test", "button.dh_pve_ups_test_deep",
                topics.test_deep, "mdi:battery-heart-variant",
            )
        if capabilities.supports_test("stop"):
            add_button(
                "test_stop", "Stop battery test", "button.dh_pve_ups_test_stop",
                topics.test_stop, "mdi:stop-circle-outline",
            )

    if snapshot is not None:
        if snapshot.battery_charge_percent is not None:
            add_sensor(
                "battery_charge", "Battery charge", "sensor.dh_pve_ups_battery_charge",
                "battery_charge_percent", unit="%", device_class="battery",
            )
        if snapshot.runtime_seconds is not None:
            add_sensor(
                "battery_runtime_minutes", "Battery runtime",
                "sensor.dh_pve_ups_battery_runtime_minutes", "battery_runtime_minutes",
                unit="min", device_class="duration",
            )
            add_sensor(
                "battery_runtime", "Battery runtime (seconds)",
                "sensor.dh_pve_ups_battery_runtime", "runtime_seconds",
                unit="s", device_class="duration", entity_category="diagnostic",
            )
        if snapshot.battery_voltage_v is not None:
            add_sensor(
                "battery_voltage", "Battery voltage", "sensor.dh_pve_ups_battery_voltage",
                "battery_voltage_v", unit="V", device_class="voltage",
                entity_category="diagnostic",
            )
        if snapshot.load_percent is not None:
            add_sensor("load", "Load", "sensor.dh_pve_ups_load", "load_percent", unit="%")
        if snapshot.nominal_real_power_w is not None:
            add_sensor(
                "nominal_real_power", "Nominal real power",
                "sensor.dh_pve_ups_nominal_real_power", "nominal_real_power_w",
                unit="W", device_class="power", entity_category="diagnostic",
            )
        if snapshot.input_voltage_v is not None:
            add_sensor(
                "input_voltage", "Input voltage", "sensor.dh_pve_ups_input_voltage",
                "input_voltage_v", unit="V", device_class="voltage",
            )
        if snapshot.output_voltage_v is not None:
            add_sensor(
                "output_voltage", "Output voltage", "sensor.dh_pve_ups_output_voltage",
                "output_voltage_v", unit="V", device_class="voltage",
            )
        if snapshot.input_frequency_hz is not None:
            add_sensor(
                "input_frequency", "Input frequency", "sensor.dh_pve_ups_input_frequency",
                "input_frequency_hz", unit="Hz", device_class="frequency",
            )
        if snapshot.output_frequency_hz is not None:
            add_sensor(
                "output_frequency", "Output frequency", "sensor.dh_pve_ups_output_frequency",
                "output_frequency_hz", unit="Hz", device_class="frequency",
            )
        if snapshot.warning_charge_percent is not None:
            add_sensor(
                "battery_charge_warning", "Battery warning threshold",
                "sensor.dh_pve_ups_battery_charge_warning", "warning_charge_percent",
                unit="%", entity_category="diagnostic",
            )
        if snapshot.low_charge_percent is not None:
            add_sensor(
                "battery_charge_low", "Battery low threshold",
                "sensor.dh_pve_ups_battery_charge_low", "low_charge_percent",
                unit="%", entity_category="diagnostic",
            )
        if snapshot.low_runtime_seconds is not None:
            add_sensor(
                "battery_runtime_low", "Low runtime threshold",
                "sensor.dh_pve_ups_battery_runtime_low", "low_runtime_seconds",
                unit="s", device_class="duration", entity_category="diagnostic",
            )
        if snapshot.test_result is not None:
            add_sensor(
                "test_result", "Last test result", "sensor.dh_pve_ups_test_result",
                "test_result", entity_category="diagnostic", icon="mdi:clipboard-check-outline",
            )
        if snapshot.beeper_status is not None:
            add_sensor(
                "beeper_status", "Beeper status", "sensor.dh_pve_ups_beeper_status",
                "beeper_status", entity_category="diagnostic", icon="mdi:volume-high",
            )

        if "ups.status" in snapshot.raw:
            add_binary(
                "on_battery", "On battery", "binary_sensor.dh_pve_ups_on_battery",
                "on_battery", "mdi:battery-arrow-down",
            )
            add_binary(
                "low_battery", "Low battery", "binary_sensor.dh_pve_ups_low_battery",
                "low_battery", "mdi:battery-alert",
            )
            add_binary(
                "replace_battery", "Replace battery", "binary_sensor.dh_pve_ups_replace_battery",
                "replace_battery", "mdi:battery-sync-outline",
            )
            add_binary(
                "overload", "Overload", "binary_sensor.dh_pve_ups_overload",
                "overload", "mdi:alert-octagon-outline",
            )
            add_binary(
                "bypass", "Bypass", "binary_sensor.dh_pve_ups_bypass",
                "bypass", "mdi:transit-connection-variant",
            )
            add_binary(
                "charging", "Charging", "binary_sensor.dh_pve_ups_charging",
                "charging", "mdi:battery-charging", entity_category="diagnostic",
            )
            add_binary(
                "discharging", "Discharging", "binary_sensor.dh_pve_ups_discharging",
                "discharging", "mdi:battery-minus", entity_category="diagnostic",
            )

    device: dict[str, Any] = {
        "identifiers": [topics.device_id],
        "name": "DH PVE UPS",
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
