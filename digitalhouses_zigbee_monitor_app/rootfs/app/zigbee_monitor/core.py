"""Read-only, multi-Zigbee2MQTT inventory and MQTT activity acquisition.

Only Zigbee2MQTT bridge/devices is authoritative for device identity.  Never
derive identity from a Home Assistant entity_id or a Zigbee2MQTT friendly name.

This module has no paho/HA/Supervisor dependency, so MQTT transports and UI
publishers can be tested independently.  It never issues Z2M requests/commands.
"""

from __future__ import annotations

import json
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Mapping

_NETWORK_ID = re.compile(r"^[a-z][a-z0-9_-]*$")
_IEEE = re.compile(r"^0x[0-9a-f]{16}$")
_RESERVED_SUFFIXES = {"/set", "/get", "/availability"}


class ZigbeeMonitorError(ValueError):
    """Invalid upstream Zigbee2MQTT data or invalid local network contract."""


@dataclass(frozen=True)
class Network:
    network_id: str
    base_topic: str
    name: str


@dataclass(frozen=True)
class Device:
    ieee_address: str
    network_id: str
    friendly_name: str
    model: str | None
    manufacturer: str | None
    device_type: str | None
    power_source: str | None = None

    @property
    def identity(self) -> tuple[str, str]:
        return self.network_id, self.ieee_address


@dataclass(frozen=True)
class Observation:
    """One incoming MQTT packet's semantic classification.

    Only `device_message` with counted=True contributes to the MQTT rankings.
    `retained` indicates retained bootstrap/replay and is intentionally excluded.
    """

    kind: str
    network_id: str | None = None
    ieee_address: str | None = None
    counted: bool = False
    inventory_changed: bool = False


@dataclass
class _NetworkRuntime:
    config: Network
    bridge_state: str = "unknown"
    inventory_observed: bool = False
    devices: dict[str, Device] = field(default_factory=dict)
    topics: dict[str, str] = field(default_factory=dict)
    availability: dict[str, str] = field(default_factory=dict)
    pending_availability: dict[str, str] = field(default_factory=dict)


def parse_networks(raw: object) -> tuple[Network, ...]:
    """Validate explicit immutable IDs and current Zigbee2MQTT base topics."""
    if not isinstance(raw, list) or not raw:
        raise ZigbeeMonitorError("zigbee2mqtt must be a non-empty list")
    networks: list[Network] = []
    seen_ids: set[str] = set()
    seen_topics: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise ZigbeeMonitorError(f"zigbee2mqtt[{index}] must be an object")
        network_id = item.get("network_id")
        base_topic = item.get("base_topic")
        name = item.get("name")
        if not isinstance(network_id, str) or not _NETWORK_ID.fullmatch(network_id):
            raise ZigbeeMonitorError(f"zigbee2mqtt[{index}].network_id is invalid")
        if (
            not isinstance(base_topic, str)
            or not base_topic
            or base_topic.startswith("/")
            or base_topic.endswith("/")
            or any(segment in ("", ".", "..", "+", "#") for segment in base_topic.split("/"))
            or any(char in base_topic for char in ("+", "#", "\x00"))
        ):
            raise ZigbeeMonitorError(f"zigbee2mqtt[{index}].base_topic is invalid")
        if not isinstance(name, str) or not name.strip():
            raise ZigbeeMonitorError(f"zigbee2mqtt[{index}].name is required")
        if network_id in seen_ids:
            raise ZigbeeMonitorError(f"duplicate network_id: {network_id}")
        if base_topic in seen_topics:
            raise ZigbeeMonitorError(f"duplicate base_topic: {base_topic}")
        for existing in seen_topics:
            if existing.startswith(base_topic + "/") or base_topic.startswith(existing + "/"):
                raise ZigbeeMonitorError("nested base_topic values are unsupported")
        seen_ids.add(network_id)
        seen_topics.add(base_topic)
        networks.append(Network(network_id, base_topic, name.strip()))
    return tuple(networks)


def _ieee(value: Any) -> str:
    if not isinstance(value, str):
        raise ZigbeeMonitorError("bridge/devices ieee_address must be a string")
    normalized = value.strip().lower()
    if not _IEEE.fullmatch(normalized):
        raise ZigbeeMonitorError(f"bridge/devices ieee_address invalid: {value!r}")
    return normalized


def _optional_text(value: Any, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ZigbeeMonitorError(f"bridge/devices {label} must be a string or null")
    return value or None


def _decode_json(payload: bytes, label: str) -> Any:
    try:
        return json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ZigbeeMonitorError(f"invalid {label} JSON") from exc


def _devices_from_bridge(raw: Any, network_id: str) -> tuple[dict[str, Device], dict[str, str]]:
    if not isinstance(raw, list):
        raise ZigbeeMonitorError("bridge/devices must be a JSON array")
    devices: dict[str, Device] = {}
    topics: dict[str, str] = {}
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ZigbeeMonitorError(f"bridge/devices[{index}] must be an object")
        # A coordinator is not an end device. It still has an IEEE.
        kind = entry.get("type")
        if kind == "Coordinator":
            continue
        if kind is not None and not isinstance(kind, str):
            raise ZigbeeMonitorError(f"bridge/devices[{index}].type must be text")
        ieee = _ieee(entry.get("ieee_address"))
        name = entry.get("friendly_name")
        if not isinstance(name, str) or not name.strip():
            raise ZigbeeMonitorError(f"bridge/devices[{index}].friendly_name is required")
        if name != name.strip() or name.startswith("/") or name.endswith("/"):
            raise ZigbeeMonitorError(f"bridge/devices[{index}].friendly_name invalid")
        if any(seg in {"", ".", "..", "+", "#"} for seg in name.split("/")):
            raise ZigbeeMonitorError(f"bridge/devices[{index}].friendly_name invalid")
        if name == "bridge" or name.startswith("bridge/"):
            raise ZigbeeMonitorError("bridge/devices friendly_name collides with bridge namespace")
        if ieee in devices:
            raise ZigbeeMonitorError(f"bridge/devices duplicate IEEE: {ieee}")
        if name in topics:
            raise ZigbeeMonitorError(f"bridge/devices duplicate friendly_name: {name!r}")
        definition = entry.get("definition")
        if definition is not None and not isinstance(definition, dict):
            raise ZigbeeMonitorError(f"bridge/devices[{index}].definition must be object/null")
        definition = definition or {}
        devices[ieee] = Device(
            ieee_address=ieee,
            network_id=network_id,
            friendly_name=name,
            model=_optional_text(definition.get("model"), "definition.model"),
            manufacturer=_optional_text(definition.get("vendor"), "definition.vendor"),
            device_type=kind,
            power_source=_optional_text(entry.get("power_source"), "power_source"),
        )
        topics[name] = ieee
    return devices, topics


class ZigbeeMonitor:
    """Multi-network stateful MQTT classifier; pure acquisition, not persistence."""

    def __init__(self, networks: tuple[Network, ...]) -> None:
        self._networks = {cfg.network_id: _NetworkRuntime(cfg) for cfg in networks}
        if len(self._networks) != len(networks):
            raise ZigbeeMonitorError("duplicate network ID")
        self._by_topic = {cfg.base_topic: self._networks[cfg.network_id] for cfg in networks}
        if len(self._by_topic) != len(networks):
            raise ZigbeeMonitorError("duplicate network base_topic")
        self._bases = tuple(sorted(self._by_topic, key=len, reverse=True))
        self._counts: dict[tuple[int, str, str], int] = defaultdict(int)
        # Actual non-retained MQTT device messages only; never infer Zigbee RF
        # connectivity or availability from this observational timestamp.
        self._latest_mqtt: dict[tuple[str, str], int] = {}

    @property
    def networks(self) -> tuple[Network, ...]:
        return tuple(runtime.config for runtime in self._networks.values())

    def add_network(self, config: Network) -> bool:
        """Upsert an auto-discovered network without resetting physical-device history.

        An existing logical ID may change base topic, but two logical networks
        must never share the same base or a nested base topic.
        """
        if not _NETWORK_ID.fullmatch(config.network_id):
            raise ZigbeeMonitorError("invalid discovered network ID")
        parse_networks([{
            "network_id": config.network_id, "base_topic": config.base_topic,
            "name": config.name,
        }])
        previous = self._networks.get(config.network_id)
        if previous is not None and previous.config == config:
            return False
        for network_id, runtime in self._networks.items():
            if network_id == config.network_id:
                continue
            old = runtime.config.base_topic
            if (old == config.base_topic or old.startswith(config.base_topic + "/")
                    or config.base_topic.startswith(old + "/")):
                raise ZigbeeMonitorError("ambiguous discovered base_topic")
        if previous is not None:
            self._by_topic.pop(previous.config.base_topic, None)
            if previous.config.base_topic != config.base_topic:
                previous.bridge_state = "unknown"
                previous.inventory_observed = False
                previous.topics.clear()
                previous.availability.clear()
                previous.pending_availability.clear()
            previous.config = config
            runtime = previous
        else:
            runtime = _NetworkRuntime(config)
            self._networks[config.network_id] = runtime
        self._by_topic[config.base_topic] = runtime
        self._bases = tuple(sorted(self._by_topic, key=len, reverse=True))
        return True

    def reset_sources(self) -> None:
        """On MQTT reconnect, invalidate observations but preserve identities/counts.

        Previously received retained bridge/device availability is not proof of
        live state after a transport interruption. Subscriptions must reconcile.
        """
        for runtime in self._networks.values():
            runtime.bridge_state = "unknown"
            runtime.inventory_observed = False
            runtime.topics.clear()
            runtime.availability.clear()
            runtime.pending_availability.clear()

    def network_status(self, network_id: str) -> dict[str, object]:
        r = self._networks[network_id]
        return {
            "network_id": r.config.network_id,
            "name": r.config.name,
            "bridge_state": r.bridge_state,
            "inventory_observed": r.inventory_observed,
            "devices": len(r.devices) if r.inventory_observed else None,
        }

    def devices(self, network_id: str) -> tuple[Device, ...]:
        return tuple(self._networks[network_id].devices.values())

    def get_device(self, network_id: str, ieee_address: str) -> Device | None:
        return self._networks[network_id].devices.get(_ieee(ieee_address))

    def availability(self, network_id: str, ieee_address: str) -> str:
        return self._networks[network_id].availability.get(_ieee(ieee_address), "unknown")

    def total_devices(self) -> int | None:
        # Partial inventory never masquerades as the number of devices in all networks.
        if not self._networks or not all(runtime.inventory_observed for runtime in self._networks.values()):
            return None
        return sum(len(runtime.devices) for runtime in self._networks.values())

    def counts_snapshot(self) -> dict[tuple[int, str, str], int]:
        """Snapshot counts for durable batch commit; do not discard until committed."""
        return dict(self._counts)

    def acknowledge_counts(self, persisted: Mapping[tuple[int, str, str], int]) -> None:
        """Subtract only committed counts, leaving any newer observations intact."""
        for key, count in persisted.items():
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                raise ZigbeeMonitorError("invalid acknowledged MQTT count")
            available = self._counts.get(key, 0)
            if count > available:
                raise ZigbeeMonitorError("cannot acknowledge more messages than observed")
        for key, count in persisted.items():
            remaining = self._counts.get(key, 0) - count
            if remaining:
                self._counts[key] = remaining
            else:
                self._counts.pop(key, None)

    def mqtt_activity_snapshot(self) -> dict[tuple[str, str], int]:
        """Newest non-retained MQTT device message time pending durable flush."""
        return dict(self._latest_mqtt)

    def acknowledge_mqtt_activity(self, persisted: Mapping[tuple[str, str], int]) -> None:
        """Do not discard a newer observation that arrived during persistence."""
        for identity, timestamp in persisted.items():
            if self._latest_mqtt.get(identity) == timestamp:
                self._latest_mqtt.pop(identity, None)

    def ingest(
        self, topic: str, payload: bytes, *, retain: bool = False, dup: bool = False,
        observed_at: int | None = None,
    ) -> Observation:
        """Classify one MQTT message; invalid bridge payload raises without state loss."""
        network: _NetworkRuntime | None = None
        suffix = ""
        for base in self._bases:
            if topic.startswith(base + "/"):
                network = self._by_topic[base]
                suffix = topic[len(base) + 1:]
                break
        if network is None:
            return Observation("unrelated")

        network_id = network.config.network_id
        if suffix == "bridge/state":
            value = payload.decode("utf-8", errors="strict")
            try:
                parsed = json.loads(value)
            except ValueError:
                parsed = value
            if isinstance(parsed, dict):
                state = parsed.get("state")
            else:
                state = parsed
            if state not in {"online", "offline"}:
                raise ZigbeeMonitorError("bridge/state must be online/offline")
            network.bridge_state = state
            return Observation("bridge_state", network_id)

        if suffix == "bridge/devices":
            new_devices, new_topics = _devices_from_bridge(
                _decode_json(payload, "bridge/devices"), network_id,
            )
            changed = network.devices != new_devices or network.topics != new_topics
            # Invalidate cached availability if an IEEE moved to a new topic.
            # A retained availability packet for the new topic will restore it.
            old_devices = network.devices
            preserved = {
                ieee: state for ieee, state in network.availability.items()
                if ieee in old_devices and ieee in new_devices
                and old_devices[ieee].friendly_name == new_devices[ieee].friendly_name
            }
            # Make changes atomically; bad inventories cannot wipe a known-good roster.
            network.devices = new_devices
            network.topics = new_topics
            for friendly, state in network.pending_availability.items():
                ieee = new_topics.get(friendly)
                if ieee is not None:
                    preserved[ieee] = state
            network.availability = preserved
            network.pending_availability.clear()
            network.inventory_observed = True
            return Observation("inventory", network_id, inventory_changed=changed)

        # Device messages are identified from the authoritative current inventory,
        # NOT from arbitrary topic text, Z2M groups or HA entity names.
        if suffix.startswith("bridge/"):
            return Observation("bridge_message", network_id)
        if suffix in network.topics:
            ieee = network.topics[suffix]
            if not retain and not dup:
                ts = int(time.time()) if observed_at is None else observed_at
                if not isinstance(ts, int) or isinstance(ts, bool) or ts < 0:
                    raise ZigbeeMonitorError("invalid observed_at for MQTT message")
                bucket = ts - ts % 60
                self._counts[(bucket, network_id, ieee)] += 1
                identity = (network_id, ieee)
                self._latest_mqtt[identity] = max(
                    self._latest_mqtt.get(identity, 0), ts
                )
            return Observation("device_message", network_id, ieee, counted=not retain and not dup)
        if suffix.endswith("/availability"):
            friendly = suffix[:-len("/availability")]
            ieee = network.topics.get(friendly)
            data = _decode_json(payload, "device availability")
            if not isinstance(data, dict) or data.get("state") not in ("online", "offline"):
                raise ZigbeeMonitorError("availability requires online/offline state")
            if ieee is None:
                # At cold boot retained availability may arrive before retained
                # bridge/devices.  Keep a bounded cache until identity is known.
                if len(network.pending_availability) >= 2048:
                    raise ZigbeeMonitorError("too many unmapped availability topics")
                network.pending_availability[friendly] = data["state"]
                return Observation("unmapped_availability", network_id)
            network.availability[ieee] = data["state"]
            return Observation("device_availability", network_id, ieee)
        if any(suffix.endswith(s) for s in _RESERVED_SUFFIXES):
            return Observation("device_control_or_unknown", network_id)
        return Observation("unmapped_message", network_id)

