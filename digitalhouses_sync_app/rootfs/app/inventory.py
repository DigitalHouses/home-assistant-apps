"""Conservative discovery of existing DigitalHouses MQTT availability topics.

No product disappearance is inferred from offline, missing, or stale MQTT data.
The inventory contains no credentials or site-specific addresses.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

MQTT_ROOT = "DigitalHouses/Global"

# These are currently published namespaces, NOT a request to rename them.
TOPIC_PRODUCTS = {
    "digitalhouses_pve_agent": "digitalhouses_pve_agent",
    "digitalhouses_plex_agent": "digitalhouses_plex_agent",
    "digitalhouses_recorder_app": "digitalhouses_recorder_app",
    "dh_network_app": "digitalhouses_network_app",
    "dh_zigbee_monitor_app": "digitalhouses_zigbee_monitor_app",
    "speedtest": "digitalhouses_speedtest_app",
    "backblaze": "digitalhouses_backblaze_app",
}
MULTI_INSTANCE = {"digitalhouses_pve_agent", "digitalhouses_plex_agent"}


def parse_availability(topic: str) -> tuple[str, str] | None:
    prefix = MQTT_ROOT + "/"
    if not topic.startswith(prefix):
        return None
    segments = topic[len(prefix):].split("/")
    if len(segments) == 2 and segments[1] == "availability":
        product = TOPIC_PRODUCTS.get(segments[0])
        if product:
            return (product, "default")
    if (
        len(segments) == 3
        and segments[0] in MULTI_INSTANCE
        and segments[1]
        and segments[2] == "availability"
    ):
        return (TOPIC_PRODUCTS[segments[0]], segments[1])
    return None


class Inventory:
    def __init__(self, path: Path):
        self.path = path
        self.known: dict[str, str] = {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self.known = {
                    str(k): str(v) for k, v in data.items()
                    if v in ("online", "offline", "unknown")
                }
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            pass

    def apply(self, topic: str, payload: str) -> bool:
        identity = parse_availability(topic)
        if identity is None or payload not in ("online", "offline"):
            return False
        key = "/".join(identity)
        # An offline retained message alone does not establish installation.
        if payload == "offline" and key not in self.known:
            return False
        if self.known.get(key) == payload:
            return False
        self.known[key] = payload
        return True

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(
            json.dumps(self.known, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temp, self.path)

