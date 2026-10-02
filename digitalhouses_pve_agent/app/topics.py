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
    refresh_operation: str
    restart_agent: str
    manifest: str
    settings_prefix: str
    diagnostic_event: str
    discovery: str
    ha_status: str
    device_id: str
    ups_scan: str
    ups_scan_state: str
    ups_scan_operation: str
    fan_calibrate: str
    update_check: str = ""
    update_install: str = ""
    update_state: str = ""
    legacy_discoveries: tuple[str, ...] = ()


@dataclass(frozen=True)
class UpsTopics:
    base: str
    state: str
    availability: str
    refresh: str
    refresh_operation: str
    beeper_set: str
    test_quick: str
    test_deep: str
    test_stop: str
    test_quick_interval_days_set: str
    test_quick_time_set: str
    test_deep_interval_days_set: str
    test_deep_time_set: str
    policy_charge_threshold_set: str
    policy_runtime_reserve_set: str
    policy_apply: str
    diagnostic_event: str
    discovery: str
    legacy_discoveries: tuple[str, ...]
    device_id: str

    @property
    def legacy_discovery(self) -> str:
        """Oldest discovery topic retained for compatibility callers/tests."""
        return self.legacy_discoveries[-1]


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
    device_id = f"dh_pve_agent_{identity.instance_id}"
    legacy_device_id = f"dh_app_pve_{identity.instance_id}"
    older_legacy_device_id = f"dh_pve_{identity.instance_id}"
    discovery_prefix = mqtt.discovery_prefix.strip("/")
    return Topics(
        base=base,
        state=f"{base}/state",
        availability=f"{base}/availability",
        refresh=f"{base}/refresh",
        refresh_operation=f"{base}/refresh/operation",
        restart_agent=f"{base}/restart",
        manifest=f"{base}/manifest",
        settings_prefix=f"{base}/settings",
        diagnostic_event=f"{base}/event/diagnostic",
        discovery=f"{discovery_prefix}/device/{device_id}/config",
        ha_status=f"{discovery_prefix}/status",
        device_id=device_id,
        ups_scan=f"{base}/ups/scan",
        ups_scan_state=f"{base}/ups/scan/state",
        ups_scan_operation=f"{base}/ups/scan/operation",
        fan_calibrate=f"{base}/fans/calibrate",
        update_check=f"{base}/update/check",
        update_install=f"{base}/update/install",
        update_state=f"{base}/update/state",
        legacy_discoveries=(
            f"{discovery_prefix}/device/{legacy_device_id}/config",
            f"{discovery_prefix}/device/{older_legacy_device_id}/config",
            f"{discovery_prefix}/device/digitalhouses_proxmox_{identity.instance_id}/config",
        ),
    )


def build_ups_topics(mqtt: MqttConfig, identity: HostIdentity) -> UpsTopics:
    pve = build_topics(mqtt, identity)
    base = f"{pve.base}/ups"
    device_id = f"dh_pve_agent_ups_{identity.instance_id}"
    legacy_device_id = f"dh_app_pve_ups_{identity.instance_id}"
    older_legacy_device_id = f"dh_pve_ups_{identity.instance_id}"
    oldest_legacy_device_id = f"dh_ups_{identity.instance_id}"
    discovery_prefix = mqtt.discovery_prefix.strip("/")
    policy_base = f"{base}/policy"
    test_schedule_base = f"{base}/test/schedule"
    return UpsTopics(
        base=base,
        state=f"{base}/state",
        availability=f"{base}/availability",
        refresh=f"{base}/refresh",
        refresh_operation=f"{base}/refresh/operation",
        beeper_set=f"{base}/beeper/set",
        test_quick=f"{base}/test/quick",
        test_deep=f"{base}/test/deep",
        test_stop=f"{base}/test/stop",
        test_quick_interval_days_set=f"{test_schedule_base}/quick/interval_days/set",
        test_quick_time_set=f"{test_schedule_base}/quick/time/set",
        test_deep_interval_days_set=f"{test_schedule_base}/deep/interval_days/set",
        test_deep_time_set=f"{test_schedule_base}/deep/time/set",
        policy_charge_threshold_set=f"{policy_base}/shutdown_battery_charge_threshold/set",
        policy_runtime_reserve_set=f"{policy_base}/shutdown_runtime_reserve/set",
        policy_apply=f"{policy_base}/apply",
        diagnostic_event=f"{base}/event/diagnostic",
        discovery=f"{discovery_prefix}/device/{device_id}/config",
        legacy_discoveries=(
            f"{discovery_prefix}/device/{legacy_device_id}/config",
            f"{discovery_prefix}/device/{older_legacy_device_id}/config",
            f"{discovery_prefix}/device/{oldest_legacy_device_id}/config",
        ),
        device_id=device_id,
    )
