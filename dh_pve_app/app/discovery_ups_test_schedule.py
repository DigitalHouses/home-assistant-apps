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

    def last_test_component(
        key: str,
        name: str,
        entity_id: str,
        test_type: str,
    ) -> dict[str, Any]:
        return {
            "platform": "sensor",
            "name": name,
            "unique_id": uid(key),
            "default_entity_id": entity_id,
            "state_topic": topics.state,
            "value_template": (
                "{{ value_json.test_schedule."
                f"{test_type}.last_result | default('Unknown', true) }}}}"
            ),
            "availability": availability,
            "availability_mode": "all",
            "entity_category": "diagnostic",
            "icon": "mdi:battery-check-outline",
            "json_attributes_topic": topics.state,
            "json_attributes_template": (
                "{{ {'last_time': value_json.test_schedule."
                f"{test_type}.last_time | default(none) }}}} | tojson }}}}"
            ),
        }

    def next_test_component(
        key: str,
        name: str,
        entity_id: str,
        test_type: str,
    ) -> dict[str, Any]:
        return {
            "platform": "sensor",
            "name": name,
            "unique_id": uid(key),
            "default_entity_id": entity_id,
            "state_topic": topics.state,
            "value_template": (
                "{{ value_json.test_schedule."
                f"{test_type}.next_due | default(none) }}}}"
            ),
            "device_class": "timestamp",
            "availability": availability,
            "availability_mode": "all",
            "entity_category": "diagnostic",
            "icon": "mdi:calendar-clock-outline",
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
        "test_state": {
            "platform": "sensor",
            "name": "Battery test state",
            "unique_id": uid("test_state"),
            "default_entity_id": "sensor.dh_pve_ups_test_state",
            "state_topic": topics.state,
            "value_template": (
                "{{ value_json.test_schedule.current_state | default('Idle') }}"
            ),
            "availability": availability,
            "availability_mode": "all",
            "entity_category": "diagnostic",
            "icon": "mdi:battery-sync-outline",
            "json_attributes_topic": topics.state,
            "json_attributes_template": (
                "{{ {'last_decision': value_json.test_schedule.last_decision "
                "| default(none)} | tojson }}"
            ),
        },
        "last_quick_test": last_test_component(
            "last_quick_test",
            "Last Quick test",
            "sensor.dh_pve_ups_last_quick_test",
            "quick",
        ),
        "next_quick_test": next_test_component(
            "next_quick_test",
            "Next Quick test",
            "sensor.dh_pve_ups_next_quick_test",
            "quick",
        ),
        "last_deep_test": last_test_component(
            "last_deep_test",
            "Last Deep test",
            "sensor.dh_pve_ups_last_deep_test",
            "deep",
        ),
        "next_deep_test": next_test_component(
            "next_deep_test",
            "Next Deep test",
            "sensor.dh_pve_ups_next_deep_test",
            "deep",
        ),
        "test_history": {
            "platform": "sensor",
            "name": "Battery test history",
            "unique_id": uid("test_history"),
            "default_entity_id": "sensor.dh_pve_ups_test_history",
            "state_topic": topics.state,
            "value_template": "{{ value_json.test_history | default([]) | count }}",
            "availability": availability,
            "availability_mode": "all",
            "entity_category": "diagnostic",
            "icon": "mdi:history",
            "json_attributes_topic": topics.state,
            "json_attributes_template": (
                "{{ {'history': value_json.test_history | default([])} | tojson }}"
            ),
        },
    }
