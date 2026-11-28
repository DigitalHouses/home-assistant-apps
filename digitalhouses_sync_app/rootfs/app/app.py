"""DigitalHouses Sync App: MQTT-only catalog, GitHub dashboard/package sync."""
from __future__ import annotations

import json
import logging
import os
import signal
import threading
import time
from datetime import datetime, timezone
import paho.mqtt.client as mqtt

from catalog_web import make_server
from discovery_contract import DiscoveryError, ProductSources, parse_sync_topic
from resource_preview import PreviewCatalog
from local_audit import LocalAuditor
from auto_sync import AutoSync
from event_journal import EventJournal
from dashboard_runtime import DashboardPublisher
from ha_core import CoreAPI
from ha_timezone import HATimezone, HAFormatter
from telemetry import TelemetryClient, TelemetryRunner

PRODUCT_ID = "digitalhouses_sync_app"
BASE = "DigitalHouses/Global/" + PRODUCT_ID
DISCOVERY = "homeassistant/device/" + PRODUCT_ID + "/config"
STARTED_AT = datetime.now(timezone.utc).isoformat()
VERSION = os.environ.get("APP_VERSION", "0.6.10-local")
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
    LOG.info("Subscribed to retained product metadata (auto-sync)")


def main() -> None:
    # Policy v2: Home Assistant App requires explicit consent before activation.
    if os.environ.get("TELEMETRY_ENABLED", "false").strip().lower() != "true":
        LOG.error("Telemetry/privacy terms not accepted; DH Sync cannot activate. "
                  "Enable telemetry_enabled in the App configuration.")
        raise SystemExit(1)

    telemetry = TelemetryClient(enabled=True, version=VERSION)
    telemetry_runner = TelemetryRunner(telemetry)
    sources = ProductSources()  # In-memory only; MQTT is the registry.
    # Publish YAML files and register the DigitalHouses panel over HA API.
    # No direct .storage edits, HA restart, or operator interaction.
    ha_timezone = HATimezone(lambda: CoreAPI().timezone())
    for handler in logging.getLogger().handlers:
        handler.setFormatter(HAFormatter(ha_timezone))
    ha_timezone.refresh()
    journal = EventJournal(debug=os.environ.get("LOG_LEVEL", "info").lower() == "debug")
    journal.backend.start(VERSION)
    auto = AutoSync(journal=journal)
    auto.publisher = DashboardPublisher(auto.root, auto.data, journal=journal)
    auto.reloader = lambda: CoreAPI().reload_configuration()
    def run_sync(*, refresh=False):
        ha_timezone.refresh()
        return auto.sync(sources.snapshot(), refresh=refresh)

    wake = threading.Event()
    ingress = make_server(
        sources, version=VERSION, port=8099, auto_status=auto.status,
        auto_sync=lambda: run_sync(refresh=True), journal=journal,
        timezone_source=ha_timezone.snapshot,
    )
    threading.Thread(target=ingress.serve_forever, daemon=True,
                     name="dh-sync-ingress").start()
    LOG.info("DH Sync v%s automatic Ingress ready on 8099", VERSION)

    def auto_loop() -> None:
        first = True
        while True:
            # Never publish from local YAML before the first MQTT subscription.
            wake.wait(timeout=None if first else 3600)
            wake.clear()
            if first:
                time.sleep(8)  # Batch the broker's retained /sync messages.
            first = False
            run_sync()

    threading.Thread(target=auto_loop, daemon=True,
                     name="dh-sync-auto").start()

    client = create_mqtt_client()
    username = os.environ.get("MQTT_USER") or None
    if username:
        client.username_pw_set(username, os.environ.get("MQTT_PASSWORD", ""))
    client.will_set(BASE + "/availability", "offline", qos=1, retain=True)

    seen = {}

    def on_message(client, userdata, message):
        if message.topic.endswith("/sync"):
            try:
                if sources.apply(message.topic, message.payload):
                    LOG.info("MQTT product registry changed: %s", message.topic)
                    product, instance = parse_sync_topic(message.topic)
                    identity = product + '/' + instance
                    current = sources.snapshot().get(identity)
                    previous = seen.get(identity)
                    if current is None:
                        seen.pop(identity, None)
                        journal.record('product_removed', identity, product=product)
                    elif previous != current:
                        seen[identity] = current
                        event = 'product_detected' if previous is None else 'product_changed'
                        detail = identity + ' · ' + str(current.get('version', ''))
                        if previous and previous.get('version') != current.get('version'):
                            event = 'product_version_changed'
                            detail = identity + ' · ' + str(previous.get('version')) + ' → ' + str(current.get('version'))
                        journal.record(event, detail, product=product)
                    wake.set()
            except DiscoveryError as exc:
                LOG.warning("Rejected MQTT source (%s): %s", message.topic, exc)
                journal.record("mqtt_rejected", str(exc), level="warning")
            return
    def subscribed(client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            # Rebuild from the broker's retained /sync set on every reconnect.
            sources.reset()
            wake.set()
        on_connect(client, userdata, flags, reason_code, properties)
        journal.record('mqtt_connected' if reason_code == 0 else 'mqtt_connect_failed',
                       str(reason_code), level='info' if reason_code == 0 else 'error')

    def disconnected(client, userdata, *args):
        journal.record('mqtt_disconnected', level='warning')

    client.on_disconnect = disconnected
    client.on_connect = subscribed
    client.on_message = on_message
    client.connect_async(
        os.environ["MQTT_HOST"],
        int(os.environ.get("MQTT_PORT", "1883")),
        keepalive=60,
    )
    def stop(signum, frame):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    telemetry_runner.start()
    try:
        client.loop_forever(retry_first_connection=True)
    except SystemExit:
        journal.backend.stop()
        raise
    except Exception:
        journal.backend.error("app_failed")
        raise
    else:
        journal.backend.stop()
    finally:
        telemetry_runner.stop()


if __name__ == "__main__":
    main()
