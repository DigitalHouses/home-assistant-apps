from __future__ import annotations

from dataclasses import dataclass

from .config import MqttConfig
from .identity import HostIdentity


@dataclass(frozen=True)
class Topics:
    base: str
    state: str
    availability: str
    refresh: str
    manifest: str
    settings_prefix: str
    discovery: str
    ha_status: str
    device_id: str


@dataclass(frozen=True)
class UpsTopics:
    state: str
    availability: str
    refresh: str
    discovery: str
    device_id: str


def build_topics(mqtt: MqttConfig, identity: HostIdentity) -> Topics:
    base = f"{mqtt.topic_prefix.rstrip('/')}/{identity.instance_id}"
    device_id = f"dh_pve_{identity.instance_id}"
    discovery_prefix = mqtt.discovery_prefix.strip("/")
    return Topics(
        base=base,
        state=f"{base}/state",
        availability=f"{base}/availability",
        refresh=f"{base}/refresh",
        manifest=f"{base}/manifest",
        settings_prefix=f"{base}/settings",
        discovery=f"{discovery_prefix}/device/{device_id}/config",
        ha_status=f"{discovery_prefix}/status",
        device_id=device_id,
    )


def build_ups_topics(mqtt: MqttConfig, identity: HostIdentity) -> UpsTopics:
    pve = build_topics(mqtt, identity)
    device_id = f"dh_ups_{identity.instance_id}"
    discovery_prefix = mqtt.discovery_prefix.strip("/")
    return UpsTopics(
        state=f"{pve.base}/ups/state",
        availability=f"{pve.base}/ups/availability",
        refresh=f"{pve.base}/ups/refresh",
        discovery=f"{discovery_prefix}/device/{device_id}/config",
        device_id=device_id,
    )
