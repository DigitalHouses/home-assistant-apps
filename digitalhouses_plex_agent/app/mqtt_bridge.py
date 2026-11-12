from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
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
        self._lock = threading.RLock()
        # Foreground-only serialization; network callbacks must never acquire it.
        self._event_lock = threading.Lock()
        self._diagnostics: dict[str, object] = {
            "state": "MQTT_PAUSED", "last_connected": None, "last_error": None,
            "last_publish": None, "last_ack": None,
            "publication_state": "paused", "reconnect_seconds": 60,
        }
        # Keep timed-out QoS1 receipts: Paho retransmits the same packet on
        # reconnect. A later foreground flush must not enqueue a duplicate.
        self._pending_events: dict[str, Any] = {}
        # Discovery is serialized by the foreground lifecycle controller.
        self._pending_discovery: tuple[str, Any] | None = None
        self._pending_discovery_cleanup: tuple[str, Any] | None = None
        self._collector_available: bool | None = None
        self._plex_api_available: bool | None = None

        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=topics.device_id,
        )
        self.client.reconnect_delay_set(60, 60)
        self.client.connect_timeout = 5.0
        self.client.max_queued_messages_set(32)
        self.client.max_inflight_messages_set(1)
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
        self.client.on_connect_fail = self._on_connect_fail
        self.client.on_publish = self._on_publish

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: object,
        flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties | None,
    ) -> None:
        if reason_code.is_failure:
            self._connection_failed(f"MQTT connection rejected: {reason_code}")
            return
        with self._lock:
            changed = not self.connected.is_set()
            self.connected.set()
            self._diagnostics.update(state="CONNECTED", last_connected=self._now(),
                                     publication_state="ready")
        if changed:
            self.log.info("MQTT connected")
        client.subscribe(self.topics.ha_status)
        client.subscribe(self.topics.refresh)
        client.subscribe(self.topics.update_check)
        client.subscribe(self.topics.update_install)
        client.subscribe(self.topics.restart_agent)
        self._publish(self.topics.app_availability, "online")
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
        self._connection_failed(f"MQTT disconnected: {reason_code}")

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def diagnostics(self) -> dict[str, object]:
        with self._lock:
            return dict(self._diagnostics)

    def _connection_failed(self, error: str) -> None:
        with self._lock:
            changed = (self._diagnostics["state"] != "MQTT_PAUSED"
                       or self._diagnostics["last_error"] is None)
            self.connected.clear()
            self._diagnostics.update(state="MQTT_PAUSED", last_error=error,
                                     publication_state="paused")
        if changed:
            self.log.warning("%s; foreground monitoring paused", error)
        self.wake_requested.set()

    def _on_connect_fail(self, client: mqtt.Client, userdata: object) -> None:
        self._connection_failed("MQTT connection attempt failed")

    def _on_publish(self, client, userdata, mid, reason_code, properties) -> None:
        # VERSION2 does not identify QoS here. QoS0 can reuse a pending QoS1 MID
        # after wrap, so only the foreground MQTTMessageInfo receipt proves ACK.
        if reason_code.is_failure:
            return
        with self._lock:
            self._diagnostics["last_publish"] = self._now()

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
            info = self._publish(self.topics.app_availability, "offline")
            if info is not None:
                try:
                    info.wait_for_publish(timeout=2.0)
                except (RuntimeError, ValueError):
                    pass
            self.client.disconnect()
        finally:
            self.client.loop_stop()

    def set_discovery_payload(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self.discovery_payload = payload

    def _publish(self, topic: str, payload: str, *, qos: int = 0,
                 retain: bool = True):
        # Never call Paho while holding _lock: callbacks may arrive while Paho
        # holds its outgoing-message mutex and need _lock for diagnostics.
        if not self.connected.is_set():
            return None
        try:
            info = self.client.publish(topic, payload=payload, qos=qos, retain=retain)
        except (OSError, ValueError, RuntimeError):
            info = None
        # In Paho 2.1 QoS1 NO_CONN means the packet is already retained in
        # _out_messages for reconnect replay. Its receipt keeps rc=NO_CONN even
        # after PUBACK, which otherwise makes wait/is_published raise forever.
        # Normalize only this known queued case to local pending SUCCESS; this
        # never means delivered. Only info.is_published() may acknowledge it.
        if info is not None and qos == 1 and info.rc == mqtt.MQTT_ERR_NO_CONN:
            info.rc = mqtt.MQTT_ERR_SUCCESS
        with self._lock:
            if info is None or info.rc != mqtt.MQTT_ERR_SUCCESS:
                self._diagnostics.update(publication_state="failed",
                                         last_error="MQTT publication failed")
                return None
            if self.connected.is_set():
                self._diagnostics["publication_state"] = (
                    "qos1_pending_ack" if qos else "qos0_local_accept"
                )
        return info

    def _publish_json(self, topic: str, payload: dict[str, object]) -> bool:
        return self._publish(topic, json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"),
        )) is not None

    def publish_discovery(self) -> bool:
        with self._lock:
            payload = self.discovery_payload
        if not self.connected.is_set():
            return False
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        pending = getattr(self, "_pending_discovery", None)
        if pending is not None:
            pending_raw, info = pending
            if not self._receipt_acknowledged(info):
                try:
                    info.wait_for_publish(timeout=2.0)
                except (RuntimeError, ValueError):
                    pass
            if not self._receipt_acknowledged(info):
                return False
            self._pending_discovery = None
            if pending_raw == raw:
                with self._lock:
                    self._diagnostics.update(last_ack=self._now(), publication_state="qos1_acked")
                return True
        info = self._publish(self.topics.discovery, raw, qos=1, retain=True)
        if info is None:
            return False
        self._pending_discovery = (raw, info)
        if not self._receipt_acknowledged(info):
            try:
                info.wait_for_publish(timeout=2.0)
            except (RuntimeError, ValueError):
                pass
        if not self._receipt_acknowledged(info):
            return False
        self._pending_discovery = None
        with self._lock:
            self._diagnostics.update(last_ack=self._now(), publication_state="qos1_acked")
        return True

    def clear_discovery_state(self, topic: str) -> bool:
        # Defense in depth: only agent state topics may be selectively cleared.
        base = self.topics.base.rstrip("/")
        if not topic.startswith(base + "/") or any(c in topic for c in "+#\x00"):
            return False
        suffix = topic[len(base) + 1:]
        if not (suffix == "state" or suffix.startswith("state/")
                or suffix in {"update/state", "agent/card"}):
            return False
        if not self.connected.is_set():
            return False
        pending = getattr(self, "_pending_discovery_cleanup", None)
        if pending is not None:
            pending_topic, receipt = pending
            if not self._receipt_acknowledged(receipt):
                try:
                    receipt.wait_for_publish(timeout=2.0)
                except (RuntimeError, ValueError):
                    pass
            if not self._receipt_acknowledged(receipt):
                return False
            self._pending_discovery_cleanup = None
            if pending_topic == topic:
                return True
        receipt = self._publish(topic, "", qos=1, retain=True)
        if receipt is None:
            return False
        self._pending_discovery_cleanup = (topic, receipt)
        if not self._receipt_acknowledged(receipt):
            try:
                receipt.wait_for_publish(timeout=2.0)
            except (RuntimeError, ValueError):
                pass
        if not self._receipt_acknowledged(receipt):
            return False
        self._pending_discovery_cleanup = None
        return True

    def publish_diagnostic_event(self, payload: dict[str, object]) -> bool:
        """Return true only after PUBACK; called by foreground, never callbacks.

        A bounded wait leaves unacknowledged events in the durable outbox. Keep
        the receipt so reconnect retries don't enqueue the same event twice.
        """
        if not self.connected.is_set():
            return False
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        key = str(payload.get("event_id") or raw)
        with self._event_lock:
            # The durable outbox can drop old events on overflow. Their Paho
            # receipts may complete later; reclaim these acknowledged orphans
            # before applying the pending bound. Preserve the current receipt
            # until its ACK is returned to the outbox so it isn't republished.
            for pending_key, receipt in list(self._pending_events.items()):
                if pending_key == key:
                    continue
                done = self._receipt_acknowledged(receipt)
                if done:
                    del self._pending_events[pending_key]
                    with self._lock:
                        self._diagnostics["last_ack"] = self._now()
            info = self._pending_events.get(key)
            if info is None:
                if len(self._pending_events) >= 32:
                    return False
                info = self._publish(self.topics.diagnostic_event, raw, qos=1, retain=False)
                if info is None:
                    return False
                self._pending_events[key] = info
            if not self._receipt_acknowledged(info):
                try:
                    info.wait_for_publish(timeout=2.0)
                except (RuntimeError, ValueError):
                    pass
            if not self._receipt_acknowledged(info):
                return False
            self._pending_events.pop(key, None)
            with self._lock:
                self._diagnostics.update(last_ack=self._now(), publication_state="qos1_acked")
            return True

    @staticmethod
    def _receipt_acknowledged(info) -> bool:
        try:
            return info.is_published()
        except (RuntimeError, ValueError):
            return False

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
        return self._publish(self.topics.state, "") is not None

    def _set_available(self, attribute: str, topic: str, available: bool,
                       force: bool) -> bool:
        with self._lock:
            if not self.connected.is_set():
                return False
            if not force and getattr(self, attribute) is available:
                return True
        if self._publish(topic, "online" if available else "offline") is None:
            return False
        with self._lock:
            setattr(self, attribute, available)
        return True

    def set_collector_available(self, available: bool, *, force: bool = False) -> bool:
        return self._set_available("_collector_available",
                                   self.topics.collector_availability, available, force)

    def set_plex_api_available(self, available: bool, *, force: bool = False) -> bool:
        return self._set_available("_plex_api_available",
                                   self.topics.plex_api_availability, available, force)
