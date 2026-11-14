"""DH Sync v0.1.3: strictly read-only MQTT product catalog.

No Home Assistant API, HA configuration mount, Git downloads or YAML apply in
the installed runtime. Resource delivery code is development-only.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt

from catalog_web import make_server
from discovery_contract import DiscoveryError, ProductSources
from inventory import Inventory
from resource_preview import PreviewCatalog

PRODUCT_ID = "digitalhouses_sync_app"
BASE = "DigitalHouses/Global/" + PRODUCT_ID
DISCOVERY = "homeassistant/device/" + PRODUCT_ID + "/config"
STARTED_AT = datetime.now(timezone.utc).isoformat()
VERSION = os.environ.get("APP_VERSION", "0.1.3-local")
STATE_PATH = Path("/data/inventory.json")
SOURCES_PATH = Path("/data/product_sources.json")

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
        "origin": {"name": "DigitalHouses Sync App", "sw_version": VERSION},
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
        "availability": [{
            "topic": BASE + "/availability",
            "payload_available": "online",
            "payload_not_available": "offline",
        }],
    }


def create_mqtt_client():
    """Use Paho 2 callback API where supported; retain Alpine Paho 1.x support.

    HAOS base image's apk py3-paho-mqtt can predate CallbackAPIVersion.
    Do not assume the host's Paho version matches CI's pip installation.
    """
    if hasattr(mqtt, "CallbackAPIVersion"):
        return mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id="digitalhouses-sync-app",
        )
    return mqtt.Client(client_id="digitalhouses-sync-app")


def on_connect(client, userdata, flags, reason_code, properties=None):
    """Accept MQTT callback shape from Paho 1.x (4 args) or 2.x (5 args)."""
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
    client.publish(
        BASE + "/sync",
        json.dumps({
            "schema": 1,
            "product_id": PRODUCT_ID,
            "type": "app",
            "version": VERSION,
            "repository": "https://github.com/DigitalHouses/home-assistant-apps",
            "product_path": "digitalhouses_sync_app",
        }),
        qos=1, retain=True,
    )
    client.subscribe("DigitalHouses/Global/+/sync", qos=1)
    client.subscribe("DigitalHouses/Global/+/+/sync", qos=1)
    client.subscribe("DigitalHouses/Global/+/availability", qos=1)
    client.subscribe("DigitalHouses/Global/+/+/availability", qos=1)
    LOG.info("Subscribed to retained product metadata (read-only)")


def main() -> None:
    inventory = Inventory(STATE_PATH)
    sources = ProductSources(SOURCES_PATH)
    # No routes can POST or mutate HA; this port is available only through
    # Supervisor's admin-only Ingress.
    ingress = make_server(sources, inventory, version=VERSION, port=8099,
                          inspect=PreviewCatalog().inspect)
    threading.Thread(target=ingress.serve_forever, daemon=True,
                     name="dh-sync-ingress").start()
    LOG.info("DH Sync v%s read-only catalog Ingress ready on 8099", VERSION)

    client = create_mqtt_client()
    username = os.environ.get("MQTT_USER") or None
    if username:
        client.username_pw_set(username, os.environ.get("MQTT_PASSWORD", ""))
    client.will_set(BASE + "/availability", "offline", qos=1, retain=True)

    def on_message(client, userdata, message):
        if message.topic.endswith("/sync"):
            try:
                if sources.apply(message.topic, message.payload):
                    sources.save()
                    LOG.info("Accepted product source: %s", message.topic)
            except DiscoveryError as exc:
                LOG.warning("Rejected MQTT source (%s): %s", message.topic, exc)
            return
        if inventory.apply(
            message.topic, message.payload.decode("utf-8", errors="replace").strip()
        ):
            inventory.save()
            LOG.info("Inventory changed: %s", sorted(inventory.known))

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
