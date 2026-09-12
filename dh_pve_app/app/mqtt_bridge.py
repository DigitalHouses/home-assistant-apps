from __future__ import annotations

import json
import logging
import queue
import threading
from dataclasses import dataclass
from typing import Any

from .config import MqttConfig
from .runtime_settings import RuntimeSettingError, RuntimeSettings
from .topics import Topics, UpsTopics


@dataclass(frozen=True)
class WillMessage:
    topic: str
    payload: str
    qos: int
    retain: bool


@dataclass(frozen=True)
class SettingUpdate:
    key: str
    value: float


def build_lwt(topics: Topics) -> WillMessage:
    return WillMessage(topics.availability, "offline", 1, True)


class MqttEvents:
    def __init__(self, topics: Topics, settings: RuntimeSettings) -> None:
        self.topics = topics
        self.settings = settings
        self.ups_topics: UpsTopics | None = None
        self.refresh_requested = threading.Event()
        self.reconnect_requested = threading.Event()
        self.ups_scan_requested = threading.Event()
        self.ups_refresh_requested = threading.Event()
        self.ups_reconnect_requested = threading.Event()
        self.setting_updates: queue.SimpleQueue[SettingUpdate] = queue.SimpleQueue()

    def configure_ups(self, topics: UpsTopics) -> None:
        self.ups_topics = topics

    def handle_ha_online(self) -> None:
        self.reconnect_requested.set()
        if self.ups_topics is not None:
            self.ups_reconnect_requested.set()

    def handle_message(self, topic: str, payload: bytes) -> bool:
        text = payload.decode("utf-8", errors="replace").strip()
        if topic == self.topics.refresh:
            if text.upper() == "PRESS":
                self.refresh_requested.set()
                return True
            return False
        if topic == self.topics.ups_scan:
            if text.upper() == "PRESS":
                self.ups_scan_requested.set()
                return True
            return False
        if self.ups_topics is not None and topic == self.ups_topics.refresh:
            if text.upper() == "PRESS":
                self.ups_refresh_requested.set()
                return True
            return False
        prefix = f"{self.topics.settings_prefix}/"
        suffix = "/set"
        if topic.startswith(prefix) and topic.endswith(suffix):
            key = topic[len(prefix):-len(suffix)]
            value = self.settings.apply(key, text)
            self.setting_updates.put(SettingUpdate(key=key, value=value))
            return True
        return False


class MqttBridge(MqttEvents):
    def __init__(
        self,
        config: MqttConfig,
        topics: Topics,
        settings: RuntimeSettings,
        discovery_payload: dict[str, Any],
        *,
        client: Any | None = None,
        publish_timeout_seconds: float = 5.0,
    ) -> None:
        super().__init__(topics, settings)
        self.config = config
        self.discovery_payload = discovery_payload
        self.publish_timeout_seconds = publish_timeout_seconds
        self.log = logging.getLogger(__name__)
        self.connected = threading.Event()
        self.wake_requested = threading.Event()
        if client is None:
            import paho.mqtt.client as mqtt
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=topics.device_id)
        self.client = client
        if config.username:
            self.client.username_pw_set(config.username, config.password)
        will = build_lwt(topics)
        self.client.will_set(will.topic, payload=will.payload, qos=will.qos, retain=will.retain)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def configure_ups(self, topics: UpsTopics) -> None:
        super().configure_ups(topics)

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if getattr(reason_code, "is_failure", False):
            self.log.error("MQTT connection rejected: %s", reason_code)
            return
        self.connected.set()
        client.subscribe(self.topics.ha_status, qos=1)
        client.subscribe(self.topics.refresh, qos=1)
        client.subscribe(self.topics.ups_scan, qos=1)
        client.subscribe(f"{self.topics.base}/ups/refresh", qos=1)
        client.subscribe(f"{self.topics.settings_prefix}/+/set", qos=1)
        if self.ups_topics is not None:
            client.publish(
                self.ups_topics.availability,
                payload="online",
                qos=1,
                retain=True,
            )
        client.publish(self.topics.availability, payload="online", qos=1, retain=True)
        self.handle_ha_online()
        self.wake_requested.set()

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties) -> None:
        self.connected.clear()
        self.wake_requested.set()

    def _setting_key(self, topic: str) -> str | None:
        prefix = f"{self.topics.settings_prefix}/"
        suffix = "/set"
        if topic.startswith(prefix) and topic.endswith(suffix):
            return topic[len(prefix):-len(suffix)]
        return None

    def _on_message(self, client, userdata, message) -> None:
        payload = bytes(message.payload)
        text = payload.decode("utf-8", errors="replace").strip()
        if message.topic == self.topics.ha_status and text.casefold() == "online":
            self.handle_ha_online()
            self.wake_requested.set()
            return
        try:
            handled = self.handle_message(message.topic, payload)
        except RuntimeSettingError as exc:
            key = self._setting_key(message.topic)
            self.log.warning("Rejected MQTT runtime setting: %s", exc)
            if key is not None:
                try:
                    self.publish_setting_value(key, self.settings.get(key))
                except RuntimeSettingError:
                    pass
            return
        if handled:
            self.wake_requested.set()

    def start(self) -> None:
        self.client.connect_async(self.config.host, self.config.port, self.config.keepalive_seconds)
        self.client.loop_start()

    def wait_connected(self, timeout: float) -> bool:
        return self.connected.wait(timeout)

    def stop(self) -> None:
        try:
            if self.connected.is_set():
                if self.ups_topics is not None:
                    self._publish(self.ups_topics.availability, "offline", retain=True)
                self._publish(self.topics.availability, "offline", retain=True)
                self.client.disconnect()
        finally:
            self.connected.clear()
            self.client.loop_stop()

    def set_discovery_payload(self, payload: dict[str, Any]) -> None:
        self.discovery_payload = payload

    def _publish(self, topic: str, payload: str, *, retain: bool) -> bool:
        if not self.connected.is_set():
            return False
        try:
            info = self.client.publish(topic, payload=payload, qos=1, retain=retain)
            if getattr(info, "rc", 1) != 0:
                return False
            info.wait_for_publish(timeout=self.publish_timeout_seconds)
            is_published = getattr(info, "is_published", None)
            return bool(is_published()) if callable(is_published) else True
        except Exception:
            self.log.exception("MQTT publish failed: %s", topic)
            return False

    def publish_discovery(self) -> bool:
        return self._publish(
            self.topics.discovery,
            json.dumps(self.discovery_payload, ensure_ascii=False, separators=(",", ":")),
            retain=True,
        )

    def publish_state(self, payload: dict[str, object]) -> bool:
        return self._publish(
            self.topics.state,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            retain=True,
        )

    def publish_ups_scan_state(self, payload: dict[str, object]) -> bool:
        return self._publish(
            self.topics.ups_scan_state,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            retain=True,
        )

    def publish_setting_value(self, key: str, value: float) -> bool:
        return self._publish(
            f"{self.topics.settings_prefix}/{key}/state",
            f"{value:g}",
            retain=True,
        )

    def publish_ups_discovery(self, payload: dict[str, object]) -> bool:
        if self.ups_topics is None:
            return False
        return self._publish(
            self.ups_topics.discovery,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            retain=True,
        )

    def clear_legacy_ups_discovery(self) -> bool:
        if self.ups_topics is None:
            return False
        return self._publish(self.ups_topics.legacy_discovery, "", retain=True)

    def publish_ups_state(self, payload: dict[str, object]) -> bool:
        if self.ups_topics is None:
            return False
        return self._publish(
            self.ups_topics.state,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            retain=True,
        )

    def publish_ups_availability(self, online: bool) -> bool:
        if self.ups_topics is None:
            return False
        return self._publish(
            self.ups_topics.availability,
            "online" if online else "offline",
            retain=True,
        )
