"""DigitalHouses Backblaze Home Assistant App."""

from __future__ import annotations

import json
import logging
import os
import signal
import threading
from datetime import datetime, timezone
from typing import Any

import paho.mqtt.client as mqtt

from backblaze import B2Client, BackblazeError
from config import load_settings
from core import build_account_state
from discovery import DEVICE_ID, build_discovery_payload
from telemetry import ensure_identity, heartbeat_if_due

APP_VERSION = os.getenv("APP_VERSION", "0.1.0-local")
STARTED_AT = datetime.now(timezone.utc).isoformat(timespec="seconds")

MQTT_BASE_TOPIC = "DigitalHouses/Global/backblaze"
STATE_TOPIC = f"{MQTT_BASE_TOPIC}/state"
COMMAND_TOPIC = f"{MQTT_BASE_TOPIC}/command"
AVAILABILITY_TOPIC = f"{MQTT_BASE_TOPIC}/availability"
DISCOVERY_TOPIC = f"homeassistant/device/{DEVICE_ID}/config"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class BackblazeApp:
    def __init__(self) -> None:
        self.settings = load_settings()
        logging.basicConfig(
            level=getattr(logging, self.settings.log_level.upper()),
            format="%(asctime)s %(levelname)s %(message)s",
        )
        self.log = logging.getLogger("digitalhouses_backblaze")
        self.stop_event = threading.Event()
        self.refresh_event = threading.Event()
        self.last_state: dict[str, Any] = {
            "api_ok": False,
            "app_version": APP_VERSION,
            "started_at": STARTED_AT,
            "last_update": None,
            "bucket_count": 0,
            "total_bytes": 0,
            "total_gib": 0.0,
            "buckets": {},
        }
        self.client = self._build_mqtt_client()

    def _build_mqtt_client(self) -> mqtt.Client:
        client = mqtt.Client(client_id=f"digitalhouses-backblaze-{DEVICE_ID}")
        username = os.getenv("MQTT_USER", "")
        if username:
            client.username_pw_set(username, os.getenv("MQTT_PASSWORD", ""))
        client.will_set(
            AVAILABILITY_TOPIC,
            payload="offline",
            qos=1,
            retain=True,
        )
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        return client

    def _on_connect(self, client, userdata, flags, rc) -> None:
        if rc != 0:
            self.log.error("MQTT connection failed with rc=%s", rc)
            return
        client.publish(AVAILABILITY_TOPIC, "online", qos=1, retain=True)
        client.subscribe(COMMAND_TOPIC, qos=1)
        self.log.info("MQTT connected")

    def _on_message(self, client, userdata, message) -> None:
        payload = message.payload.decode("utf-8", errors="replace").strip().lower()
        if message.topic == COMMAND_TOPIC and payload == "refresh":
            self.log.info("Manual Backblaze refresh requested")
            self.refresh_event.set()

    def _publish(self, topic: str, payload: Any, *, retain: bool = True) -> None:
        if not isinstance(payload, str):
            payload = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        result = self.client.publish(topic, payload, qos=1, retain=retain)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            self.log.warning("MQTT publish failed for %s: rc=%s", topic, result.rc)

    def _publish_state_and_discovery(self, buckets: list[dict[str, Any]]) -> None:
        topics = {
            "state": STATE_TOPIC,
            "command": COMMAND_TOPIC,
            "availability": AVAILABILITY_TOPIC,
        }
        discovery = build_discovery_payload(
            app_version=APP_VERSION,
            topics=topics,
            buckets=buckets,
        )
        self._publish(DISCOVERY_TOPIC, discovery)
        self._publish(STATE_TOPIC, self.last_state)

    def refresh(self) -> None:
        if not self.settings.application_key_id or not self.settings.application_key:
            self.last_state = {
                **self.last_state,
                "api_ok": False,
                "last_update": utc_now(),
                "error": "Backblaze application key is not configured",
            }
            self._publish_state_and_discovery(
                list(self.last_state.get("buckets", {}).values())
            )
            self.log.warning("Backblaze application key is not configured")
            return

        try:
            buckets = B2Client(
                self.settings.application_key_id,
                self.settings.application_key,
            ).collect()
            self.last_state = build_account_state(
                buckets,
                app_version=APP_VERSION,
                started_at=STARTED_AT,
                updated_at=utc_now(),
            )
            self._publish_state_and_discovery(buckets)
            self.log.info(
                "Backblaze refresh complete: buckets=%d storage=%.3f GiB",
                len(buckets),
                self.last_state["total_gib"],
            )
        except BackblazeError as exc:
            self.last_state = {
                **self.last_state,
                "api_ok": False,
                "last_update": utc_now(),
                "error": str(exc),
            }
            self._publish_state_and_discovery(
                list(self.last_state.get("buckets", {}).values())
            )
            self.log.error("Backblaze refresh failed: %s", exc)

    def _telemetry_worker(self) -> None:
        ensure_identity()
        if not self.settings.telemetry_enabled:
            return
        if heartbeat_if_due(APP_VERSION):
            self.log.info("Usage telemetry heartbeat sent")

    def run(self) -> None:
        host = os.getenv("MQTT_HOST", "")
        port = int(os.getenv("MQTT_PORT", "1883"))
        if not host:
            raise RuntimeError("MQTT_HOST is not set")

        self.client.connect(host, port, keepalive=60)
        self.client.loop_start()
        self._publish(AVAILABILITY_TOPIC, "online")
        threading.Thread(
            target=self._telemetry_worker,
            name="telemetry",
            daemon=True,
        ).start()

        try:
            self.refresh()
            interval = self.settings.refresh_interval_hours * 60 * 60
            while not self.stop_event.is_set():
                self.refresh_event.wait(timeout=interval)
                self.refresh_event.clear()
                if not self.stop_event.is_set():
                    self.refresh()
        finally:
            self._publish(AVAILABILITY_TOPIC, "offline")
            self.client.loop_stop()
            self.client.disconnect()

    def stop(self, *_args) -> None:
        self.stop_event.set()
        self.refresh_event.set()


def main() -> None:
    app = BackblazeApp()
    signal.signal(signal.SIGTERM, app.stop)
    signal.signal(signal.SIGINT, app.stop)
    app.run()


if __name__ == "__main__":
    main()
