"""Home Assistant single-device MQTT Discovery payload."""
from .core import Resident

BASE = "DigitalHouses/Global/dh_presence_app"
DISCOVERY = "homeassistant/device/dh_presence_app/config"
EVENT_TYPES = ["arrival", "departure", "gps_in", "gps_out", "wifi_in", "wifi_out"]


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
            "value_template": "{{ 'ON' if value_json.status == 'home' else 'OFF' }}",
            "json_attributes_topic": topic("state"),
            "json_attributes_template": "{{ {'mode': value_json.mode, 'residents': value_json.residents, 'residents_total': value_json.residents_total, 'residents_home': value_json.residents_home} | tojson }}",
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
            "value_template": "{{ 'ON' if value_json.residents['" + r.key + "'].gps == 'home' else 'OFF' }}",
            "payload_on": "ON", "payload_off": "OFF",
            "availability_mode": "all",
            "availability": [availability, {"topic": topic("gps/"+r.key+"/availability"), "payload_available": "online", "payload_not_available": "offline"}]
        }
        components[r.key + "_distance"] = {
            "platform": "sensor", "name": r.name + " distance",
            "unique_id": prefix + "_distance", "default_entity_id": "sensor." + prefix + "_distance",
            "state_topic": topic("distance/"+r.key), "unit_of_measurement": "km",
            "state_class": "measurement", "suggested_display_precision": 2,
            "availability_mode": "all",
            "availability": [availability, {"topic": topic("distance/"+r.key+"/availability"), "payload_available": "online", "payload_not_available": "offline"}]
        }
    return {"device": {"identifiers": ["dh_presence_app"], "name": "DigitalHouses Presence App",
                       "manufacturer": "DigitalHouses", "model": "Presence App", "sw_version": version},
            "origin": {"name": "DigitalHouses Presence App", "sw_version": version}, "components": components}


def with_cleanup(previous: dict, current: dict) -> dict:
    components = dict(current["components"])
    for key, old in previous.get("components", {}).items():
        if key not in components:
            components[key] = {"platform": old["platform"]}
    return {**current, "components": components}
