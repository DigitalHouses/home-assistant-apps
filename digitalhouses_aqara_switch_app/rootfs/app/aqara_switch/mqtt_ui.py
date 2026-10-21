"""Home Assistant MQTT Device Discovery for the Aqara App scan pilot.

No device-control commands, only app-local SCAN request topic.
"""
from __future__ import annotations
import json

PREFIX = "dh_aqara_switch_app"
ROOT = "DigitalHouses/Global/" + PREFIX
DISCOVERY_TOPIC = "homeassistant/device/" + PREFIX + "/config"
AVAILABILITY = ROOT + "/availability"
SCAN_REQUEST = ROOT + "/command/scan"


def configuration(version: str) -> dict:
    device = {
        "identifiers": ["digitalhouses_aqara_switch_app"],
        "name": "DigitalHouses Aqara Switch App",
        "manufacturer": "DigitalHouses",
        "model": "Aqara Switch App",
        "sw_version": version,
    }
    origin = {
        "name": "DigitalHouses Aqara Switch App",
        "sw_version": version,
        "support_url": "https://github.com/DigitalHouses/home-assistant-apps",
    }

    def sensor(key: str, name: str, state: str, attrs: bool = False):
        data = {
            "platform": "sensor", "name": name,
            "unique_id": PREFIX + "_" + key,
            "default_entity_id": "sensor." + PREFIX + "_" + key,
            "state_topic": ROOT + "/" + state,
            "value_template": "{{ value_json.state }}",
            "entity_category": "diagnostic",
        }
        if attrs:
            data["json_attributes_topic"] = ROOT + "/" + state
            data["json_attributes_template"] = "{{ value_json | tojson }}"
        return data

    components = {
        "card": sensor("card", "Статус", "card", True),
        "devices_details": sensor("devices_details", "Выключатели", "devices", True),
        "scan_state": sensor("scan_state", "Сканирование", "scan_state", True),
        "scan_details": sensor("scan_details", "Последнее сканирование", "scan_details", True),
        "problems": sensor("problems", "Проблемы", "problems", True),
        "version": {
            "platform": "sensor", "name": "Версия",
            "unique_id": PREFIX + "_version",
            "default_entity_id": "sensor." + PREFIX + "_version",
            "state_topic": ROOT + "/version",
            "entity_category": "diagnostic",
        },
        "scan": {
            "platform": "button", "name": "Сканировать",
            "unique_id": PREFIX + "_scan",
            "default_entity_id": "button." + PREFIX + "_scan",
            "command_topic": SCAN_REQUEST, "payload_press": "SCAN",
            "entity_category": "config",
        },
    }
    return {
        "device": device,
        "origin": origin,
        "availability": [{"topic": AVAILABILITY}],
        "components": components,
    }


def wire_payload(version: str) -> str:
    return json.dumps(configuration(version), ensure_ascii=False,
                      separators=(",", ":"))
