"""Home Assistant MQTT Device Discovery for the Electrica App scan pilot.

No device-control commands, only app-local SCAN request topic.
"""
from __future__ import annotations
import json

PREFIX = "dh_electrica_app"
ROOT = "DigitalHouses/Global/" + PREFIX
DISCOVERY_TOPIC = "homeassistant/device/" + PREFIX + "/config"
AVAILABILITY = ROOT + "/availability"
SCAN_REQUEST = ROOT + "/command/scan"
PRODUCT_ID = "digitalhouses_electrica_app"
SYNC_TOPIC = "DigitalHouses/Global/" + PRODUCT_ID + "/sync"


def sync_payload(version: str) -> dict:
    """DH Sync product identity. Dashboard placement lives in DH Sync YAML."""
    return {
        "schema": 1,
        "product_id": PRODUCT_ID,
        "type": "app",
        "version": version,
        "repository": "https://github.com/DigitalHouses/home-assistant-apps",
        "product_path": PRODUCT_ID,
    }


def configuration(version: str) -> dict:
    device = {
        "identifiers": ["digitalhouses_electrica_app"],
        "name": "DigitalHouses Electrica App",
        "manufacturer": "DigitalHouses",
        "model": "Electrica App",
        "sw_version": version,
    }
    origin = {
        "name": "DigitalHouses Electrica App",
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
        return data

    components = {
        "card": sensor("card", "Статус", "card", True),
        "devices_details": sensor("devices_details", "Выключатели", "devices", True),
        "scan_state": sensor("scan_state", "Сканирование", "scan_state", True),
        "scan_details": sensor("scan_details", "Последнее сканирование", "scan_details", True),
        "problems": sensor("problems", "Проблемы", "problems", True),
        "last_action": sensor("last_action", "Последнее нажатие", "last_action", True),
        "version": {
            "platform": "sensor", "name": "Версия",
            "unique_id": PREFIX + "_version",
            "default_entity_id": "sensor." + PREFIX + "_version",
            "state_topic": ROOT + "/version",
            "entity_category": "diagnostic",
        },
        "latest_version": {
            "platform":"sensor","name":"Последняя версия",
            "unique_id":PREFIX+"_latest_version","default_entity_id":"sensor."+PREFIX+"_latest_version",
            "state_topic":ROOT+"/latest_version","entity_category":"diagnostic",
        },
        "update_available": {
            "platform":"binary_sensor","name":"Доступна новая версия",
            "unique_id":PREFIX+"_update_available","default_entity_id":"binary_sensor."+PREFIX+"_update_available",
            "state_topic":ROOT+"/update_available","payload_on":"ON","payload_off":"OFF",
            "entity_category":"diagnostic",
        },
        "refresh_state": sensor("refresh_state","Обновление данных","refresh_state",True),
        "last_refresh": {
            "platform":"sensor","name":"Последнее обновление",
            "unique_id":PREFIX+"_last_refresh","default_entity_id":"sensor."+PREFIX+"_last_refresh",
            "state_topic":ROOT+"/last_refresh","entity_category":"diagnostic",
        },
    }
    for key, name, command, payload in (
        ("refresh","Обновить","refresh","REFRESH"),
        ("check_updates","Версия","check_updates","CHECK"),
    ):
        components[key] = {"platform":"button","name":name,
            "unique_id":PREFIX+"_"+key,"default_entity_id":"button."+PREFIX+"_"+key,
            "command_topic":ROOT+"/command/"+command,"payload_press":payload,
            "entity_category":"config"}
    return {
        "device": device,
        "origin": origin,
        "availability": [{"topic": AVAILABILITY}],
        "components": components,
    }


def wire_payload(version: str) -> str:
    return json.dumps(configuration(version), ensure_ascii=False,
                      separators=(",", ":"))
