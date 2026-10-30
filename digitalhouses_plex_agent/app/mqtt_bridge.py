from __future__ import annotations

import json
import logging
import threading
from typing import Any

import paho.mqtt.client as mqtt

from .config import AppConfig
from .discovery import Topics, state_group_topic


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
        self.check_updates_requested = threading.Event()
        self.install_update_requested = threading.Event()
        self.restart_requested = threading.Event()
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
        client.subscribe(self.topics.update_check)
        client.subscribe(self.topics.update_install)
        client.subscribe(self.topics.restart_agent)
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
        if message.retain and message.topic in {
            self.topics.refresh, self.topics.update_check,
            self.topics.update_install, self.topics.restart_agent,
        }:
            self.log.warning("Ignoring retained Plex control command")
            return
        if message.topic == self.topics.ha_status and payload.casefold() == "online":
            self.republish_requested.set()
            self.wake_requested.set()
        elif payload == "PRESS":
            controls = {
                self.topics.refresh: self.refresh_requested,
                self.topics.update_check: self.check_updates_requested,
                self.topics.update_install: self.install_update_requested,
                self.topics.restart_agent: self.restart_requested,
            }
            event = controls.get(message.topic)
            if event is not None:
                event.set()
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

    def _publish_json(self, topic: str, payload: dict[str, object]) -> bool:
        info = self.client.publish(
            topic,
            payload=json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            qos=0,
            retain=True,
        )
        return info.rc == mqtt.MQTT_ERR_SUCCESS

    def publish_discovery(self) -> bool:
        return self._publish_json(self.topics.discovery, self.discovery_payload)

    def publish_diagnostic_event(self, payload: dict[str, object]) -> bool:
        """PVE-compatible HA event, non-retained and QoS 1."""
        if not self.connected.is_set():
            return False
        info = self.client.publish(
            self.topics.diagnostic_event,
            payload=json.dumps(
                payload, ensure_ascii=False, separators=(",", ":")
            ),
            qos=1,
            retain=False,
        )
        return info.rc == mqtt.MQTT_ERR_SUCCESS

    def publish_agent_card(self, payload: dict[str, object]) -> bool:
        if not self.connected.is_set():
            return False
        return self._publish_json(self.topics.agent_card_state, payload)

    def publish_update_state(self, payload: dict[str, object]) -> bool:
        if not self.connected.is_set():
            return False
        return self._publish_json(self.topics.update_state, payload)

    def publish_state(self, payload: dict[str, object]) -> bool:
        """Legacy monolithic publisher retained for compatibility tests/tools."""
        return self._publish_json(self.topics.state, payload)

    def publish_state_group(self, group: str, payload: dict[str, object]) -> bool:
        return self._publish_json(state_group_topic(self.topics, group), payload)

    def clear_legacy_state(self) -> bool:
        info = self.client.publish(
            self.topics.state,
            payload="",
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
