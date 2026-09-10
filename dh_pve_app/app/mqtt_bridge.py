from __future__ import annotations

import queue
import threading
from dataclasses import dataclass

from .runtime_settings import RuntimeSettings
from .topics import Topics


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
    return WillMessage(
        topic=topics.availability,
        payload="offline",
        qos=1,
        retain=True,
    )


class MqttEvents:
    def __init__(self, topics: Topics, settings: RuntimeSettings) -> None:
        self.topics = topics
        self.settings = settings
        self.refresh_requested = threading.Event()
        self.reconnect_requested = threading.Event()
        self.setting_updates: queue.SimpleQueue[SettingUpdate] = queue.SimpleQueue()

    def handle_message(self, topic: str, payload: bytes) -> bool:
        if topic == self.topics.refresh:
            if payload.decode("utf-8", errors="replace").strip().upper() == "PRESS":
                self.refresh_requested.set()
                return True
            return False

        prefix = f"{self.topics.settings_prefix}/"
        suffix = "/set"
        if topic.startswith(prefix) and topic.endswith(suffix):
            key = topic[len(prefix):-len(suffix)]
            raw = payload.decode("utf-8", errors="replace").strip()
            value = self.settings.apply(key, raw)
            self.setting_updates.put(SettingUpdate(key=key, value=value))
            return True

        return False
