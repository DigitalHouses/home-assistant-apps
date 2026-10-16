"""Home Assistant single-device MQTT Discovery payload."""
from .core import Resident

BASE = "DigitalHouses/Global/dh_presence_app"
DISCOVERY = "homeassistant/device/dh_presence_app/config"
EVENT_TYPES = ["arrival", "departure", "gps_in", "gps_out", "wifi_in", "wifi_out", "wifi_lost"]


def topic(suffix: str) -> str:
    return f"{BASE}/{suffix}"


def discovery(version: str, residents: list[Resident]) -> dict:
    availability = {"topic": topic("availability"), "payload_available": "online", "payload_not_available": "offline"}
    aggregate = [availability, {"topic": topic("presence_observed"), "payload_available": "online", "payload_not_available": "offline"}]
    components = {
        "residents_home": {
            "platform": "binary_sensor", "name": "Residents home",
            "unique_id": "dh_presence_app_residents_home",
            "default_entity_id": "binary_sensor.dh_presence_app_residents_home",
            "state_topic": topic("state"),
            "value_template": "{{ 'ON' if value_json.status == 'home' else ('OFF' if value_json.status == 'not_home' else 'None') }}",
            "json_attributes_topic": topic("state"),
            "json_attributes_template": "{{ {'mode': value_json.mode, 'residents': value_json.residents, 'residents_total': value_json.residents_total, 'residents_home': value_json.residents_home, 'gps_freshness_seconds': value_json.gps_freshness_seconds} | tojson }}",
            "payload_on": "ON", "payload_off": "OFF",
            "availability": aggregate, "availability_mode": "all"
        },
        "event": {
            "platform": "event", "name": "Event",
            "unique_id": "dh_presence_app_event", "default_entity_id": "event.dh_presence_app_event",
            "state_topic": topic("event"), "event_types": EVENT_TYPES, "availability": availability
        },
        "version": {
            "platform": "sensor", "name": "Version", "unique_id": "dh_presence_app_version",
            "default_entity_id": "sensor.dh_presence_app_version",
            "state_topic": topic("diagnostics"), "value_template": "{{ value_json.version }}",
            "entity_category": "diagnostic", "availability": availability
        },
        "started_at": {
            "platform": "sensor", "name": "Started at", "unique_id": "dh_presence_app_started_at",
            "default_entity_id": "sensor.dh_presence_app_started_at",
            "state_topic": topic("diagnostics"), "value_template": "{{ value_json.started_at }}",
            "device_class": "timestamp", "entity_category": "diagnostic", "availability": availability
        },
        "mode": {
            "platform": "select", "name": "Presence mode",
            "unique_id": "dh_presence_app_mode",
            "default_entity_id": "select.dh_presence_app_mode",
            "icon": "mdi:map-marker-radius",
            "entity_category": "config",
            "options": ["gps", "wifi", "hybrid"],
            "command_topic": topic("mode/set"),
            "state_topic": topic("mode/state"),
            "qos": 1,
            "retain": False,
            "availability": availability
        },
        "notify_presence": {
            "platform": "switch", "name": "Notify · Presence",
            "unique_id": "dh_presence_app_notify_presence",
            "default_entity_id": "switch.dh_presence_app_notify_presence",
            "icon": "mdi:home-account",
            "entity_category": "config",
            "command_topic": topic("notifications/presence/set"),
            "state_topic": topic("notifications/presence/state"),
            "payload_on": "ON", "payload_off": "OFF",
            "state_on": "ON", "state_off": "OFF",
            "qos": 1, "retain": False,
            "availability": availability
        },
        "notify_gps": {
            "platform": "switch", "name": "Notify · GPS",
            "unique_id": "dh_presence_app_notify_gps",
            "default_entity_id": "switch.dh_presence_app_notify_gps",
            "icon": "mdi:crosshairs-gps",
            "entity_category": "config",
            "command_topic": topic("notifications/gps/set"),
            "state_topic": topic("notifications/gps/state"),
            "payload_on": "ON", "payload_off": "OFF",
            "state_on": "ON", "state_off": "OFF",
            "qos": 1, "retain": False,
            "availability": availability
        },
        "notify_wifi": {
            "platform": "switch", "name": "Notify · Wi-Fi",
            "unique_id": "dh_presence_app_notify_wifi",
            "default_entity_id": "switch.dh_presence_app_notify_wifi",
            "icon": "mdi:wifi",
            "entity_category": "config",
            "command_topic": topic("notifications/wifi/set"),
            "state_topic": topic("notifications/wifi/state"),
            "payload_on": "ON", "payload_off": "OFF",
            "state_on": "ON", "state_off": "OFF",
            "qos": 1, "retain": False,
            "availability": availability
        },
        "ping": {
            "platform": "switch", "name": "Detection · PING",
            "unique_id": "dh_presence_app_ping",
            "default_entity_id": "switch.dh_presence_app_ping",
            "icon": "mdi:lan-connect", "entity_category": "config",
            "command_topic": topic("probes/ping/set"),
            "state_topic": topic("probes/ping/state"),
            "payload_on": "ON", "payload_off": "OFF",
            "state_on": "ON", "state_off": "OFF",
            "qos": 1, "retain": False, "availability": availability
        },
        "arp": {
            "platform": "switch", "name": "Detection · ARP",
            "unique_id": "dh_presence_app_arp",
            "default_entity_id": "switch.dh_presence_app_arp",
            "icon": "mdi:lan-check", "entity_category": "config",
            "command_topic": topic("probes/arp/set"),
            "state_topic": topic("probes/arp/state"),
            "payload_on": "ON", "payload_off": "OFF",
            "state_on": "ON", "state_off": "OFF",
            "qos": 1, "retain": False, "availability": availability
        },
        "card": {
            "platform": "sensor", "name": "Operation status",
            "unique_id": "dh_presence_app_card", "default_entity_id": "sensor.dh_presence_app_card",
            "state_topic": topic("operations"),
            "value_template": "{{ value_json.card.state }}",
            "json_attributes_topic": topic("operations"),
            "json_attributes_template": "{{ value_json.card | tojson }}",
            "entity_category": "diagnostic", "availability": availability
        },
        "refresh": {
            "platform": "button", "name": "Refresh",
            "unique_id": "dh_presence_app_refresh", "default_entity_id": "button.dh_presence_app_refresh",
            "command_topic": topic("command"), "payload_press": "REFRESH",
            "entity_category": "config", "availability": availability
        },
        "refresh_state": {
            "platform": "sensor", "name": "Refresh status",
            "unique_id": "dh_presence_app_refresh_state",
            "default_entity_id": "sensor.dh_presence_app_refresh_state",
            "state_topic": topic("operations"),
            "value_template": "{{ value_json.refresh_state }}",
            "entity_category": "diagnostic", "availability": availability
        },
        "last_refresh": {
            "platform": "sensor", "name": "Last refresh",
            "unique_id": "dh_presence_app_last_refresh",
            "default_entity_id": "sensor.dh_presence_app_last_refresh",
            "state_topic": topic("operations"),
            "value_template": "{{ value_json.last_refresh or 'unknown' }}",
            "device_class": "timestamp", "entity_category": "diagnostic", "availability": availability
        },
        "check_updates": {
            "platform": "button", "name": "Check version",
            "unique_id": "dh_presence_app_check_updates",
            "default_entity_id": "button.dh_presence_app_check_updates",
            "command_topic": topic("command"), "payload_press": "CHECK_UPDATES",
            "entity_category": "config", "availability": availability
        },
        "latest_version": {
            "platform": "sensor", "name": "Latest release",
            "unique_id": "dh_presence_app_latest_version",
            "default_entity_id": "sensor.dh_presence_app_latest_version",
            "state_topic": topic("release"),
            "value_template": "{{ value_json.latest_version or 'unknown' }}",
            "entity_category": "diagnostic", "availability": availability
        },
        "update_available": {
            "platform": "binary_sensor", "name": "Update available",
            "unique_id": "dh_presence_app_update_available",
            "default_entity_id": "binary_sensor.dh_presence_app_update_available",
            "state_topic": topic("release"),
            "value_template": "{{ 'ON' if value_json.update_available else 'OFF' }}",
            "availability": [availability, {
                "topic": topic("release/availability"),
                "payload_available": "online", "payload_not_available": "offline"
            }],
            "availability_mode": "all"
        },
        "source_status": {
            "platform": "sensor", "name": "Source status", "unique_id": "dh_presence_app_source_status",
            "default_entity_id": "sensor.dh_presence_app_source_status",
            "state_topic": topic("diagnostics"),
            "value_template": "{{ value_json.source_status }}",
            "entity_category": "diagnostic", "availability": availability
        }
    }
    for r in residents:
        prefix = "dh_presence_app_" + r.key
        components[r.key + "_gps_home"] = {
            "platform": "binary_sensor", "name": r.name + " GPS home",
            "unique_id": prefix + "_gps_home",
            "default_entity_id": "binary_sensor." + prefix + "_gps_home",
            "state_topic": topic("state"),
            "value_template": "{{ 'ON' if value_json.residents['" + r.key + "'].gps == 'home' else ('OFF' if value_json.residents['" + r.key + "'].gps == 'not_home' else 'None') }}",
            "json_attributes_topic": topic("state"),
            "json_attributes_template": "{{ {'gps_reported_at': value_json.residents['" + r.key + "'].gps_reported_at} | tojson }}",
            "payload_on": "ON", "payload_off": "OFF",
            "availability_mode": "all",
            "availability": [availability, {"topic": topic("gps/"+r.key+"/availability"), "payload_available": "online", "payload_not_available": "offline"}]
        }
        components[r.key + "_wifi_home"] = {
            "platform": "binary_sensor", "name": r.name + " Wi-Fi home",
            "unique_id": prefix + "_wifi_home",
            "default_entity_id": "binary_sensor." + prefix + "_wifi_home",
            "state_topic": topic("state"),
            "value_template": "{{ 'ON' if value_json.residents['" + r.key + "'].wifi == 'home' else ('OFF' if value_json.residents['" + r.key + "'].wifi == 'not_home' else 'None') }}",
            "json_attributes_topic": topic("state"),
            "json_attributes_template": "{{ {'wifi_last_verified_at': value_json.residents['" + r.key + "'].wifi_last_verified_at, 'wifi_last_probe_at': value_json.residents['" + r.key + "'].wifi_last_probe_at, 'wifi_probe_result': value_json.residents['" + r.key + "'].wifi_probe_result} | tojson }}",
            "payload_on": "ON", "payload_off": "OFF",
            "availability_mode": "all",
            "availability": [
                availability,
                {"topic": topic("wifi/" + r.key + "/availability"),
                 "payload_available": "online", "payload_not_available": "offline"}
            ]
        }
        components[r.key + "_distance"] = {
            "platform": "sensor", "name": r.name + " distance",
            "unique_id": prefix + "_distance", "default_entity_id": "sensor." + prefix + "_distance",
            "state_topic": topic("distance/"+r.key), "unit_of_measurement": "km",
            "state_class": "measurement", "suggested_display_precision": 2,
            "availability_mode": "all",
            "availability": [availability, {"topic": topic("distance/"+r.key+"/availability"), "payload_available": "online", "payload_not_available": "offline"}]
        }
    return {"device": {"identifiers": ["dh_presence_app"], "name": "DH Presence",
                       "manufacturer": "DigitalHouses", "model": "Presence App", "sw_version": version},
            "origin": {"name": "DigitalHouses Presence App", "sw_version": version}, "components": components}


def with_cleanup(previous: dict, current: dict) -> dict:
    components = dict(current["components"])
    for key, old in previous.get("components", {}).items():
        if key not in components:
            components[key] = {"platform": old["platform"]}
    return {**current, "components": components}
