"""Stable MQTT entities for read-only PVE vzdump history."""
from __future__ import annotations

from .discovery_identity import canonicalize_component_unique_ids


def backup_components(topics) -> dict[str, dict]:
    base = f"{topics.base}/backup"
    availability = [{
        "topic": topics.availability, "payload_available": "online",
        "payload_not_available": "offline",
    }]
    components = {
        "backup_history": {
            "platform": "sensor", "name": "Backup history",
            "default_entity_id": "sensor.dh_pve_agent_backup_history",
            "state_topic": base + "/history",
            "value_template": "{{ value_json.status | default('unavailable') }}",
            "json_attributes_topic": base + "/history",
            "json_attributes_template": (
                "{{ {'runs': value_json.runs | default([]), "
                "'coverage': value_json.coverage | default('unavailable'), "
                "'jobs_coverage': value_json.jobs_coverage | default('unavailable'), "
                "'observed_at': value_json.observed_at | default(none), "
                "'details_limited': value_json.details_limited | default(false)} | tojson }}"
            ),
            "availability": availability, "entity_category": "diagnostic",
            "icon": "mdi:backup-restore",
        },
        "backup_history_limit": {
            "platform": "number", "name": "Backup history limit",
            "default_entity_id": "number.dh_pve_agent_backup_history_limit",
            "command_topic": base + "/history_limit/set",
            "state_topic": base + "/history_limit/state",
            "min": 1, "max": 50, "step": 1, "mode": "box",
            "qos": 1, "retain": False,
            "availability": availability, "entity_category": "config",
            "icon": "mdi:format-list-numbered",
        },
        "backup_event": {
            "platform": "event", "name": "Backup",
            "default_entity_id": "event.dh_pve_agent_backup",
            "state_topic": base + "/event",
            "event_types": ["backup_job_failed", "backup_job_completed"],
            "qos": 1,
            "availability": availability, "entity_category": "diagnostic",
            "icon": "mdi:backup-restore",
        },
    }
    canonicalize_component_unique_ids(components)
    return components
