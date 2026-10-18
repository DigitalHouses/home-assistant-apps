"""Passive Zigbee2MQTT discovery from its authoritative MQTT bridge messages.

Discovery deliberately never sends Zigbee2MQTT requests and never subscribes
to all broker traffic. MQTT wildcard probes cover base topics with 1..3 parts.
A candidate is accepted only after its coordinator IEEE can be verified.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

_COORDINATOR = re.compile(r"^0x[0-9a-f]{16}$")
_REJECT_ROOT = {"homeassistant", "DigitalHouses", "$SYS"}
MAX_TOPIC_LEVELS = 3
DISCOVERY_FILTERS = tuple(
    f"{'/'.join(['+'] * depth)}/bridge/{suffix}"
    for depth in range(1, MAX_TOPIC_LEVELS + 1)
    for suffix in ("devices", "info")
)


@dataclass(frozen=True)
class Discovery:
    base_topic: str
    coordinator_ieee: str


def discovery_from_bridge(topic: str, payload: bytes) -> Discovery | None:
    """Return verified Z2M identity, or None for unknown/invalid broker traffic.

    In particular, bridge/state alone is not a network-identity proof.
    """
    if not isinstance(topic, str) or not topic:
        return None
    base, sep, suffix = topic.rpartition("/bridge/")
    if not sep or suffix not in ("info", "devices"):
        return None
    parts = base.split("/")
    if not 1 <= len(parts) <= MAX_TOPIC_LEVELS:
        return None
    if parts[0] in _REJECT_ROOT or any(
        not part or part in {"+", "#", ".", ".."} for part in parts
    ):
        return None
    try:
        data = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    coordinator = None
    if suffix == "info":
        if isinstance(data, dict) and isinstance(data.get("coordinator"), dict):
            coordinator = data["coordinator"].get("ieee_address")
    elif isinstance(data, list):
        coordinators = [
            entry.get("ieee_address") for entry in data
            if isinstance(entry, dict) and entry.get("type") == "Coordinator"
        ]
        if len(coordinators) == 1:
            coordinator = coordinators[0]
    if not isinstance(coordinator, str):
        return None
    ieee = coordinator.strip().lower()
    if not _COORDINATOR.fullmatch(ieee):
        return None
    return Discovery(base_topic=base, coordinator_ieee=ieee)
