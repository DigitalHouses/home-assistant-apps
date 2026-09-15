from __future__ import annotations

import re
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
    diagnostic_event: str
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
    beeper_set: str
    test_quick: str
    test_deep: str
    test_stop: str
    test_quick_interval_days_set: str
    test_quick_time_set: str
    test_deep_interval_days_set: str
    test_deep_time_set: str
    policy_on_battery_delay_set: str
    policy_power_restore_delay_set: str
    policy_apply: str
    diagnostic_event: str
    discovery: str
    legacy_discovery: str
    device_id: str


_GROUP_SEGMENT = re.compile(r"^[A-Za-z0-9_.-]+$")


def _group_topic(root: str, group: str) -> str:
    parts = group.split("/")
    if not group or any(
        not part or part in {".", ".."} or _GROUP_SEGMENT.fullmatch(part) is None
        for part in parts
    ):
        raise ValueError(f"invalid MQTT state group: {group!r}")
    return f"{root}/{'/'.join(parts)}"


def state_group_topic(topics: Topics, group: str) -> str:
    return _group_topic(topics.state, group)


def ups_state_group_topic(topics: UpsTopics, group: str) -> str:
    return _group_topic(topics.state, group)


def build_topics(mqtt: MqttConfig, identity: HostIdentity) -> Topics:
    base = f"{mqtt.topic_prefix.rstrip('/')}/{identity.instance_id}"
    device_id = f"dh_app_pve_{identity.instance_id}"
    discovery_prefix = mqtt.discovery_prefix.strip("/")
    return Topics(
        base=base,
        state=f"{base}/state",
        availability=f"{base}/availability",
        refresh=f"{base}/refresh",
        manifest=f"{base}/manifest",
        settings_prefix=f"{base}/settings",
        diagnostic_event=f"{base}/event/diagnostic",
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
    test_schedule_base = f"{pve.base}/ups/test/schedule"
    return UpsTopics(
        state=f"{pve.base}/ups/state",
        availability=f"{pve.base}/ups/availability",
        refresh=f"{pve.base}/ups/refresh",
        beeper_set=f"{pve.base}/ups/beeper/set",
        test_quick=f"{pve.base}/ups/test/quick",
        test_deep=f"{pve.base}/ups/test/deep",
        test_stop=f"{pve.base}/ups/test/stop",
        test_quick_interval_days_set=f"{test_schedule_base}/quick/interval_days/set",
        test_quick_time_set=f"{test_schedule_base}/quick/time/set",
        test_deep_interval_days_set=f"{test_schedule_base}/deep/interval_days/set",
        test_deep_time_set=f"{test_schedule_base}/deep/time/set",
        policy_on_battery_delay_set=f"{policy_base}/on_battery_delay/set",
        policy_power_restore_delay_set=f"{policy_base}/power_restore_delay/set",
        policy_apply=f"{policy_base}/apply",
        diagnostic_event=f"{pve.base}/ups/event/diagnostic",
        discovery=f"{discovery_prefix}/device/{device_id}/config",
        legacy_discovery=f"{discovery_prefix}/device/{legacy_device_id}/config",
        device_id=device_id,
    )
