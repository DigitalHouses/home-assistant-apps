from __future__ import annotations

from typing import Any, Callable

from .topics import UpsTopics


def build_test_schedule_components(
    topics: UpsTopics,
    *,
    uid: Callable[[str], str],
    app_availability: dict[str, str],
) -> dict[str, Any]:
    availability = [app_availability]

    def interval_component(
        key: str,
        name: str,
        entity_id: str,
        test_type: str,
        command_topic: str,
    ) -> dict[str, Any]:
        return {
            "platform": "number",
            "name": name,
            "unique_id": uid(key),
            "default_entity_id": entity_id,
            "state_topic": topics.state,
            "value_template": (
                "{{ value_json.test_schedule."
                f"{test_type}.interval_days | default(0) }}}}"
            ),
            "command_topic": command_topic,
            "min": 0,
            "max": 3650,
            "step": 1,
            "unit_of_measurement": "d",
            "mode": "box",
            "availability": availability,
            "availability_mode": "all",
            "icon": "mdi:calendar-sync-outline",
        }

    def time_component(
        key: str,
        name: str,
        entity_id: str,
        test_type: str,
        command_topic: str,
    ) -> dict[str, Any]:
        return {
            "platform": "time",
            "name": name,
            "unique_id": uid(key),
            "default_entity_id": entity_id,
            "state_topic": topics.state,
            "value_template": (
                "{{ (value_json.test_schedule."
                f"{test_type}.preferred_time | default('12:00')) ~ ':00' }}}}"
            ),
            "command_topic": command_topic,
            "availability": availability,
            "availability_mode": "all",
            "icon": "mdi:clock-outline",
        }

    return {
        "test_quick_interval_days": interval_component(
            "test_quick_interval_days",
            "Quick test interval",
            "number.dh_pve_ups_quick_test_interval_days",
            "quick",
            topics.test_quick_interval_days_set,
        ),
        "test_quick_time": time_component(
            "test_quick_time",
            "Quick test time",
            "time.dh_pve_ups_quick_test_time",
            "quick",
            topics.test_quick_time_set,
        ),
        "test_deep_interval_days": interval_component(
            "test_deep_interval_days",
            "Deep test interval",
            "number.dh_pve_ups_deep_test_interval_days",
            "deep",
            topics.test_deep_interval_days_set,
        ),
        "test_deep_time": time_component(
            "test_deep_time",
            "Deep test time",
            "time.dh_pve_ups_deep_test_time",
            "deep",
            topics.test_deep_time_set,
        ),
    }
