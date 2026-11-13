"""DH Sync inventory-only preview: passive MQTT observer, no YAML writes."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt

from inventory import Inventory

PRODUCT_ID = "digitalhouses_sync_app"
BASE = "DigitalHouses/Global/" + PRODUCT_ID
DISCOVERY = "homeassistant/device/" + PRODUCT_ID + "/config"
STARTED_AT = datetime.now(timezone.utc).isoformat()
VERSION = os.environ.get("APP_VERSION", "0.0.1-local")
STATE_PATH = Path("/data/inventory.json")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("dh_sync")


def device_discovery() -> dict:
    return {
        "device": {
            "identifiers": [PRODUCT_ID],
            "name": "DigitalHouses Sync",
            "manufacturer": "DigitalHouses",
            "model": "Sync App",
            "sw_version": VERSION,
        },
        "origin": {
            "name": "DigitalHouses Sync App",
            "sw_version": VERSION,
        },
        "components": {
            "version": {
                "platform": "sensor",
                "unique_id": "dh_sync_app_version_id",
                "default_entity_id": "sensor.dh_sync_app_version",
                "name": "Version",
                "entity_category": "diagnostic",
                "state_topic": BASE + "/diagnostics",
                "value_template": "{{ value_json.version }}",
            },
            "started": {
                "platform": "sensor",
                "unique_id": "dh_sync_app_started_at_id",
                "default_entity_id": "sensor.dh_sync_app_started_at",
                "name": "Started at",
                "entity_category": "diagnostic",
                "device_class": "timestamp",
                "state_topic": BASE + "/diagnostics",
                "value_template": "{{ value_json.started_at }}",
            },
        },
        "availability": [
            {
                "topic": BASE + "/availability",
                "payload_available": "online",
                "payload_not_available": "offline",
            }
        ],
    }


def main() -> None:
    inventory = Inventory(STATE_PATH)
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id="digitalhouses-sync-app",
    )
    username = os.environ.get("MQTT_USER") or None
    if username:
        client.username_pw_set(username, os.environ.get("MQTT_PASSWORD", ""))
    client.will_set(BASE + "/availability", "offline", qos=1, retain=True)

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code != 0:
            LOG.error("MQTT connect failed: %s", reason_code)
            return
        client.publish(DISCOVERY, json.dumps(device_discovery()), qos=1, retain=True)
        client.publish(
            BASE + "/diagnostics",
            json.dumps({"version": VERSION, "started_at": STARTED_AT}),
            qos=1, retain=True,
        )
        client.publish(BASE + "/availability", "online", qos=1, retain=True)
        client.subscribe("DigitalHouses/Global/+/availability", qos=1)
        client.subscribe("DigitalHouses/Global/+/+/availability", qos=1)
        LOG.info("MQTT observer active; managed YAML writes remain disabled")

    def on_message(client, userdata, message):
        if inventory.apply(
            message.topic, message.payload.decode("utf-8", errors="replace").strip()
        ):
            inventory.save()
            LOG.info("Inventory updated: %s", sorted(inventory.known))

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect_async(
        os.environ["MQTT_HOST"],
        int(os.environ.get("MQTT_PORT", "1883")),
        keepalive=60,
    )
    client.loop_forever(retry_first_connection=True)


if __name__ == "__main__":
    main()

