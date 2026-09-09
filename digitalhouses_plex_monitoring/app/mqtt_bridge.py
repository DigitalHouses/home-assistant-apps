from __future__ import annotations

import json
import logging
import threading
from typing import Any

import paho.mqtt.client as mqtt

from .config import AppConfig
from .discovery import Topics


class MqttBridge:
    def __init__(
        self,
        config: AppConfig,
        topics: Topics,
        discovery_payload: dict[str, Any],
    ) -> None:
        self.config = config
        self.topics = topics
        self.discovery_payload = discovery_payload
        self.log = logging.getLogger(__name__)

        self.refresh_requested = threading.Event()
        self.republish_requested = threading.Event()
        self.wake_requested = threading.Event()
        self.connected = threading.Event()
        self._collector_available: bool | None = None
        self._plex_api_available: bool | None = None

        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=topics.device_id,
        )
        if config.mqtt.username:
            self.client.username_pw_set(
                config.mqtt.username,
                config.mqtt.password,
            )
        self.client.will_set(
            topics.app_availability,
            payload="offline",
            qos=0,
            retain=True,
        )
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: object,
        flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties | None,
    ) -> None:
        if reason_code.is_failure:
            self.log.error("MQTT connection rejected: %s", reason_code)
            return
        self.log.info("MQTT connected")
        self.connected.set()
        client.subscribe(self.topics.ha_status)
        client.subscribe(self.topics.refresh)
        client.publish(
            self.topics.app_availability,
            payload="online",
            qos=0,
            retain=True,
        )
        self.republish_requested.set()
        self.wake_requested.set()

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: object,
        disconnect_flags: mqtt.DisconnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties | None,
    ) -> None:
        self.connected.clear()
        self.log.warning("MQTT disconnected: %s", reason_code)

    def _on_message(
        self,
        client: mqtt.Client,
        userdata: object,
        message: mqtt.MQTTMessage,
    ) -> None:
        try:
            payload = message.payload.decode("utf-8", errors="replace").strip()
        except Exception:
            payload = ""
        if message.topic == self.topics.ha_status and payload.casefold() == "online":
            self.republish_requested.set()
            self.wake_requested.set()
        elif message.topic == self.topics.refresh and payload == "PRESS":
            self.refresh_requested.set()
            self.wake_requested.set()

    def start(self) -> None:
        self.client.connect_async(
            self.config.mqtt.host,
            self.config.mqtt.port,
            self.config.mqtt.keepalive_seconds,
        )
        self.client.loop_start()

    def stop(self) -> None:
        try:
            if self.connected.is_set():
                self.client.publish(
                    self.topics.app_availability,
                    payload="offline",
                    qos=0,
                    retain=True,
                ).wait_for_publish(timeout=2.0)
                self.client.disconnect()
        finally:
            self.client.loop_stop()

    def set_discovery_payload(self, payload: dict[str, Any]) -> None:
        self.discovery_payload = payload

    def publish_discovery(self) -> bool:
        info = self.client.publish(
            self.topics.discovery,
            payload=json.dumps(
                self.discovery_payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            qos=0,
            retain=True,
        )
        return info.rc == mqtt.MQTT_ERR_SUCCESS

    def publish_state(self, payload: dict[str, object]) -> bool:
        info = self.client.publish(
            self.topics.state,
            payload=json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            qos=0,
            retain=True,
        )
        return info.rc == mqtt.MQTT_ERR_SUCCESS

    def set_collector_available(
        self,
        available: bool,
        *,
        force: bool = False,
    ) -> bool:
        if not force and self._collector_available is available:
            return True
        info = self.client.publish(
            self.topics.collector_availability,
            payload="online" if available else "offline",
            qos=0,
            retain=True,
        )
        if info.rc == mqtt.MQTT_ERR_SUCCESS:
            self._collector_available = available
            return True
        return False

    def set_plex_api_available(
        self,
        available: bool,
        *,
        force: bool = False,
    ) -> bool:
        if not force and self._plex_api_available is available:
            return True
        info = self.client.publish(
            self.topics.plex_api_availability,
            payload="online" if available else "offline",
            qos=0,
            retain=True,
        )
        if info.rc == mqtt.MQTT_ERR_SUCCESS:
            self._plex_api_available = available
            return True
        return False
