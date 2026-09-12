from __future__ import annotations

from typing import Any

from .topics import UpsTopics


def build_ups_test_schedule_components(
    topics: UpsTopics,
    *,
    device_id: str,
    app_availability: dict[str, str],
) -> dict[str, Any]:
    def uid(component: str) -> str:
        return f"{device_id}_{component}"

    availability = [app_availability]
    return {
        "test_quick_interval_days": {
            "platform": "number",
            "name": "Quick test interval",
            "unique_id": uid("test_quick_interval_days"),
            "default_entity_id": "number.dh_pve_ups_quick_test_interval_days",
            "state_topic": topics.state,
            "value_template": "{{ value_json.test_schedule.quick.interval_days | default(30) }}",
            "command_topic": topics.test_quick_interval_days_set,
            "min": 0,
            "max": 3650,
            "step": 1,
            "unit_of_measurement": "d",
            "mode": "box",
            "availability": availability,
            "availability_mode": "all",
            "icon": "mdi:calendar-refresh",
        },
        "test_quick_time": {
            "platform": "time",
            "name": "Quick test time",
            "unique_id": uid("test_quick_time"),
            "default_entity_id": "time.dh_pve_ups_quick_test_time",
            "state_topic": topics.state,
            "value_template": (
                "{{ (value_json.test_schedule.quick.preferred_time | default('12:00')) ~ ':00' }}"
            ),
            "command_topic": topics.test_quick_time_set,
            "availability": availability,
            "availability_mode": "all",
            "icon": "mdi:clock-outline",
        },
        "test_deep_interval_days": {
            "platform": "number",
            "name": "Deep test interval",
            "unique_id": uid("test_deep_interval_days"),
            "default_entity_id": "number.dh_pve_ups_deep_test_interval_days",
            "state_topic": topics.state,
            "value_template": "{{ value_json.test_schedule.deep.interval_days | default(180) }}",
            "command_topic": topics.test_deep_interval_days_set,
            "min": 0,
            "max": 3650,
            "step": 1,
            "unit_of_measurement": "d",
            "mode": "box",
            "availability": availability,
            "availability_mode": "all",
            "icon": "mdi:calendar-refresh",
        },
        "test_deep_time": {
            "platform": "time",
            "name": "Deep test time",
            "unique_id": uid("test_deep_time"),
            "default_entity_id": "time.dh_pve_ups_deep_test_time",
            "state_topic": topics.state,
            "value_template": (
                "{{ (value_json.test_schedule.deep.preferred_time | default('13:00')) ~ ':00' }}"
            ),
            "command_topic": topics.test_deep_time_set,
            "availability": availability,
            "availability_mode": "all",
            "icon": "mdi:clock-outline",
        },
    }
