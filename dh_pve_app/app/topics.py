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
    ups_scan: str
    ups_scan_state: str


@dataclass(frozen=True)
class UpsTopics:
    state: str
    availability: str
    refresh: str
    test_quick: str
    test_deep: str
    test_stop: str
    policy_on_battery_delay_set: str
    policy_power_restore_delay_set: str
    policy_apply: str
    discovery: str
    legacy_discovery: str
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
        ups_scan=f"{base}/ups/scan",
        ups_scan_state=f"{base}/ups/scan/state",
    )


def build_ups_topics(mqtt: MqttConfig, identity: HostIdentity) -> UpsTopics:
    pve = build_topics(mqtt, identity)
    device_id = f"dh_pve_ups_{identity.instance_id}"
    legacy_device_id = f"dh_ups_{identity.instance_id}"
    discovery_prefix = mqtt.discovery_prefix.strip("/")
    policy_base = f"{pve.base}/ups/policy"
    return UpsTopics(
        state=f"{pve.base}/ups/state",
        availability=f"{pve.base}/ups/availability",
        refresh=f"{pve.base}/ups/refresh",
        test_quick=f"{pve.base}/ups/test/quick",
        test_deep=f"{pve.base}/ups/test/deep",
        test_stop=f"{pve.base}/ups/test/stop",
        policy_on_battery_delay_set=f"{policy_base}/on_battery_delay/set",
        policy_power_restore_delay_set=f"{policy_base}/power_restore_delay/set",
        policy_apply=f"{policy_base}/apply",
        discovery=f"{discovery_prefix}/device/{device_id}/config",
        legacy_discovery=f"{discovery_prefix}/device/{legacy_device_id}/config",
        device_id=device_id,
    )
