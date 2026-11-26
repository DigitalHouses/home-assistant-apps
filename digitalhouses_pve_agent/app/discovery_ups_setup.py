"""HA MQTT entities for guided NUT setup, available before UPS selection."""
from __future__ import annotations

from .ups_setup import driver_options

STAGES = {
    "install": ("Установить NUT", "mdi:package-variant-closed"),
    "driver": ("Настроить драйвер NUT", "mdi:usb"),
    "server": ("Исправить NUT Server", "mdi:server"),
    "primary": ("Исправить NUT PRIMARY", "mdi:server-security"),
    "monitor": ("Исправить NUT Monitor", "mdi:shield-sync"),
    "activate": ("Активировать Shutdown PVE", "mdi:power"),
}


def components(topics) -> dict[str, dict[str, object]]:
    topic = f"{topics.base}/ups/setup"
    availability = [{"topic": topics.availability,
                     "payload_available": "online", "payload_not_available": "offline"}]
    uid = lambda suffix: f"{topics.device_id}_ups_setup_{suffix}"
    result: dict[str, dict[str, object]] = {
        "ups_setup": {
            "platform": "sensor",
            "name": "UPS setup",
            "unique_id": uid("status"),
            "default_entity_id": "sensor.dh_pve_agent_ups_setup",
            "state_topic": f"{topic}/state",
            "value_template": "{{ value_json.state | default('unknown') }}",
            "json_attributes_topic": f"{topic}/state",
            "json_attributes_template": (
                "{{ {'ready':value_json.ready | default(false), "
                "'usb':value_json.usb | default({}), "
                "'driver':value_json.driver | default({}), "
                "'nut':value_json.nut | default({}), "
                "'primary':value_json.primary | default({}), "
                "'monitor':value_json.monitor | default({}), "
                "'shutdown':value_json.shutdown | default({}), "
                "'ups':value_json.ups | default({}), "
                "'checks':value_json.checks | default({}), "
                "'issues':value_json.issues | default([]), "
                "'actions':value_json.actions | default({}), "
                "'operation':value_json.operation | default({}), "
                "'transport':value_json.transport | default('unknown')} | tojson }}"
            ),
            "availability": availability, "availability_mode": "all",
            "entity_category": "diagnostic", "icon": "mdi:shield-home",
        },
        "ups_setup_driver_select": {
            "platform": "select", "name": "UPS NUT driver",
            "unique_id": uid("driver"),
            "default_entity_id": "select.dh_pve_agent_ups_driver",
            "state_topic": f"{topic}/state",
            "value_template": "{{ value_json.driver.selected | default('Выберите драйвер') }}",
            "command_topic": f"{topic}/driver/set",
            "options": ["Выберите драйвер", *driver_options()],
            "availability": availability, "availability_mode": "all",
            "entity_category": "config", "icon": "mdi:usb",
        },
    }
    for stage, (label, icon) in STAGES.items():
        result[f"ups_setup_can_{stage}"] = {
            "platform": "binary_sensor",
            "name": f"UPS setup can {stage}",
            "unique_id": uid("can_" + stage),
            "default_entity_id": f"binary_sensor.dh_pve_agent_ups_setup_can_{stage}",
            "state_topic": f"{topic}/state",
            "value_template": (
                "{{ 'ON' if value_json.actions." + stage + " | default(false) else 'OFF' }}"
            ),
            "payload_on": "ON", "payload_off": "OFF",
            "availability": availability, "availability_mode": "all",
            "entity_category": "diagnostic",
            "entity_registry_visible_default": False,
            "icon": "mdi:check-circle-outline",
        }
        result[f"ups_setup_{stage}"] = {
            "platform": "button", "name": label,
            "unique_id": uid(stage),
            "default_entity_id": f"button.dh_pve_agent_ups_setup_{stage}",
            "command_topic": f"{topic}/{stage}",
            "payload_press": "PRESS",
            "availability": availability,
            "availability_mode": "all",
            "entity_category": "config", "icon": icon,
        }
    return result
