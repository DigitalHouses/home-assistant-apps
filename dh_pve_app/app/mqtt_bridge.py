from __future__ import annotations

import json
import logging
import queue
import re
import threading
from dataclasses import dataclass
from typing import Any

from .config import MqttConfig
from .runtime_settings import LEGACY_SETTING_KEYS, RuntimeSettingError, RuntimeSettings
from .topics import (
    Topics,
    UpsTopics,
    state_group_topic,
    ups_state_group_topic,
)
from .ups_policy import PolicyValidationError, parse_policy_value
from .ups_test_schedule import (
    TestScheduleError,
    parse_interval_days_payload,
    parse_time_command_payload,
)


_PROBLEM_ID = re.compile(r"^[a-z0-9_]+$")


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


@dataclass(frozen=True)
class TestScheduleUpdate:
    test_type: str
    field: str
    value: int | str


@dataclass(frozen=True)
class PolicyDraftUpdate:
    key: str
    value: int


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
        self.fan_calibration_requested = threading.Event()
        self.ups_refresh_requested = threading.Event()
        self.ups_test_quick_requested = threading.Event()
        self.ups_test_deep_requested = threading.Event()
        self.ups_test_stop_requested = threading.Event()
        self.ups_reconnect_requested = threading.Event()
        self.ups_policy_apply_requested = threading.Event()
        self.ups_beeper_updates: queue.SimpleQueue[bool] = queue.SimpleQueue()
        self.setting_updates: queue.SimpleQueue[SettingUpdate] = queue.SimpleQueue()
        self.ups_test_schedule_updates: queue.SimpleQueue[TestScheduleUpdate] = queue.SimpleQueue()
        self.ups_policy_updates: queue.SimpleQueue[PolicyDraftUpdate] = queue.SimpleQueue()

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
        if topic == self.topics.fan_calibrate:
            if text.upper() == "PRESS":
                self.fan_calibration_requested.set()
                return True
            return False
        if self.ups_topics is not None and topic == self.ups_topics.refresh:
            if text.upper() == "PRESS":
                self.ups_refresh_requested.set()
                return True
            return False
        if self.ups_topics is not None and topic == self.ups_topics.test_quick:
            if text.upper() == "PRESS":
                self.ups_test_quick_requested.set()
                return True
            return False
        if self.ups_topics is not None and topic == self.ups_topics.test_deep:
            if text.upper() == "PRESS":
                self.ups_test_deep_requested.set()
                return True
            return False
        if self.ups_topics is not None and topic == self.ups_topics.test_stop:
            if text.upper() == "PRESS":
                self.ups_test_stop_requested.set()
                return True
            return False
        if self.ups_topics is not None and topic == self.ups_topics.beeper_set:
            normalized = text.upper()
            if normalized == "ON":
                self.ups_beeper_updates.put(True)
                return True
            if normalized == "OFF":
                self.ups_beeper_updates.put(False)
                return True
            return False
        if self.ups_topics is not None:
            policy_topics = {
                self.ups_topics.policy_charge_threshold_set: (
                    "shutdown_battery_charge_threshold_percent"
                ),
                self.ups_topics.policy_runtime_reserve_set: "runtime_reserve_seconds",
            }
            policy_key = policy_topics.get(topic)
            if policy_key is not None:
                value = parse_policy_value(policy_key, text)
                self.ups_policy_updates.put(PolicyDraftUpdate(key=policy_key, value=value))
                return True
            if topic == self.ups_topics.policy_apply:
                if text.upper() == "PRESS":
                    self.ups_policy_apply_requested.set()
                    return True
                return False

            schedule_topics = {
                self.ups_topics.test_quick_interval_days_set: (
                    "quick",
                    "interval_days",
                    parse_interval_days_payload,
                ),
                self.ups_topics.test_quick_time_set: (
                    "quick",
                    "preferred_time",
                    parse_time_command_payload,
                ),
                self.ups_topics.test_deep_interval_days_set: (
                    "deep",
                    "interval_days",
                    parse_interval_days_payload,
                ),
                self.ups_topics.test_deep_time_set: (
                    "deep",
                    "preferred_time",
                    parse_time_command_payload,
                ),
            }
            schedule_target = schedule_topics.get(topic)
            if schedule_target is not None:
                test_type, field, parser = schedule_target
                value = parser(text)
                self.ups_test_schedule_updates.put(
                    TestScheduleUpdate(test_type=test_type, field=field, value=value)
                )
                return True

        prefix = f"{self.topics.settings_prefix}/"
        suffix = "/set"
        if topic.startswith(prefix) and topic.endswith(suffix):
            key = topic[len(prefix):-len(suffix)]
            if key in LEGACY_SETTING_KEYS:
                return False
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
        client.subscribe(self.topics.fan_calibrate, qos=1)
        client.subscribe(f"{self.topics.base}/ups/refresh", qos=1)
        client.subscribe(f"{self.topics.base}/ups/beeper/set", qos=1)
        client.subscribe(f"{self.topics.base}/ups/test/quick", qos=1)
        client.subscribe(f"{self.topics.base}/ups/test/deep", qos=1)
        client.subscribe(f"{self.topics.base}/ups/test/stop", qos=1)
        client.subscribe(f"{self.topics.base}/ups/test/schedule/quick/interval_days/set", qos=1)
        client.subscribe(f"{self.topics.base}/ups/test/schedule/quick/time/set", qos=1)
        client.subscribe(f"{self.topics.base}/ups/test/schedule/deep/interval_days/set", qos=1)
        client.subscribe(f"{self.topics.base}/ups/test/schedule/deep/time/set", qos=1)
        if self.ups_topics is not None:
            client.subscribe(self.ups_topics.policy_charge_threshold_set, qos=1)
            client.subscribe(self.ups_topics.policy_runtime_reserve_set, qos=1)
            client.subscribe(self.ups_topics.policy_apply, qos=1)
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
        except TestScheduleError as exc:
            self.log.warning("Отклонено значение расписания тестов UPS: %s", exc)
            return
        except PolicyValidationError as exc:
            self.log.warning("Отклонено значение UPS Trigger Policy: %s", exc)
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

    @staticmethod
    def _validate_problem_id(problem_id: str) -> str:
        if not isinstance(problem_id, str) or _PROBLEM_ID.fullmatch(problem_id) is None:
            raise ValueError(f"invalid problem id: {problem_id!r}")
        return problem_id

    def _problem_topic(self, problem_id: str, suffix: str) -> str:
        problem_id = self._validate_problem_id(problem_id)
        return f"{self.topics.base}/problems/{problem_id}/{suffix}"

    def _ups_problem_topic(self, problem_id: str, suffix: str) -> str:
        problem_id = self._validate_problem_id(problem_id)
        if self.ups_topics is None:
            raise RuntimeError("UPS MQTT topics are not configured")
        return f"{self.ups_topics.base}/problems/{problem_id}/{suffix}"

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

    def publish_diagnostic_event(self, payload: dict[str, object]) -> bool:
        return self._publish(
            self.topics.diagnostic_event,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            retain=False,
        )

    def publish_problem_metric(
        self,
        problem_id: str,
        payload: dict[str, object],
    ) -> bool:
        return self._publish(
            self._problem_topic(problem_id, "metric"),
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            retain=True,
        )

    def publish_problem_state(self, problem_id: str, active: bool) -> bool:
        if not isinstance(active, bool):
            raise ValueError("problem state must be bool")
        return self._publish(
            self._problem_topic(problem_id, "state"),
            "ON" if active else "OFF",
            retain=True,
        )

    def publish_problem_aggregate(self, count: int) -> bool:
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("problem aggregate count must be a non-negative integer")
        return self._publish(
            f"{self.topics.base}/problems/aggregate",
            str(count),
            retain=True,
        )

    def publish_problem_presentation(self, payload: dict[str, object]) -> bool:
        return self._publish(
            f"{self.topics.base}/problems/presentation",
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            retain=True,
        )

    def clear_legacy_pve_discovery(self) -> bool:
        ok = True
        for topic in self.topics.legacy_discoveries:
            published = self._publish(topic, "", retain=True)
            ok = published and ok
        return ok

    def clear_legacy_state(self) -> bool:
        discovery_ok = self.clear_legacy_pve_discovery()
        state_ok = self._publish(self.topics.state, "", retain=True)
        return discovery_ok and state_ok

    def publish_state_group(self, group: str, payload: dict[str, object]) -> bool:
        return self._publish(
            state_group_topic(self.topics, group),
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
        ok = True
        for topic in self.ups_topics.legacy_discoveries:
            published = self._publish(topic, "", retain=True)
            ok = published and ok
        return ok

    def clear_legacy_ups_state(self) -> bool:
        if self.ups_topics is None:
            return False
        return self._publish(self.ups_topics.state, "", retain=True)

    def publish_ups_state(self, payload: dict[str, object]) -> bool:
        if self.ups_topics is None:
            return False
        return self._publish(
            self.ups_topics.state,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            retain=True,
        )

    def publish_ups_diagnostic_event(self, payload: dict[str, object]) -> bool:
        if self.ups_topics is None:
            return False
        return self._publish(
            self.ups_topics.diagnostic_event,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            retain=False,
        )

    def publish_ups_problem_state(self, problem_id: str, active: bool) -> bool:
        if self.ups_topics is None:
            return False
        if not isinstance(active, bool):
            raise ValueError("UPS problem state must be bool")
        return self._publish(
            self._ups_problem_topic(problem_id, "state"),
            "ON" if active else "OFF",
            retain=True,
        )

    def publish_ups_problem_aggregate(self, count: int) -> bool:
        if self.ups_topics is None:
            return False
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("UPS problem aggregate count must be a non-negative integer")
        return self._publish(
            f"{self.ups_topics.base}/problems/aggregate",
            str(count),
            retain=True,
        )

    def publish_ups_problem_presentation(self, payload: dict[str, object]) -> bool:
        if self.ups_topics is None:
            return False
        return self._publish(
            f"{self.ups_topics.base}/problems/presentation",
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            retain=True,
        )

    def publish_ups_state_group(self, group: str, payload: dict[str, object]) -> bool:
        if self.ups_topics is None:
            return False
        return self._publish(
            ups_state_group_topic(self.ups_topics, group),
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
