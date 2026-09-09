from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import AppConfig, entity_prefix
from .models import BuildInfo


@dataclass(frozen=True)
class Topics:
    base: str
    state: str
    app_availability: str
    collector_availability: str
    refresh: str
    discovery: str
    ha_status: str
    device_id: str


def build_topics(config: AppConfig) -> Topics:
    instance = config.general.instance_id
    device_id = f"digitalhouses_plex_monitoring_{instance}"
    topic_prefix = config.mqtt.topic_prefix.rstrip(chr(47))
    base = topic_prefix if instance == "plex" else f"{topic_prefix}/{instance}"
    return Topics(
        base=base,
        state=f"{base}/state",
        app_availability=f"{base}/availability",
        collector_availability=f"{base}/collector_availability",
        refresh=f"{base}/refresh",
        discovery=(
            f"{config.mqtt.discovery_prefix.strip('/')}/device/{device_id}/config"
        ),
        ha_status=f"{config.mqtt.discovery_prefix.strip('/')}/status",
        device_id=device_id,
    )


def _availability(topic: str) -> dict[str, str]:
    return {
        "topic": topic,
        "payload_available": "online",
        "payload_not_available": "offline",
    }


def _component(
    *,
    platform: str,
    name: str,
    key: str,
    entity_id: str,
    state_topic: str,
    value_template: str,
    app_availability: str,
    collector_availability: str | None = None,
    diagnostic: bool = False,
    **extra: Any,
) -> dict[str, Any]:
    availability = [_availability(app_availability)]
    if collector_availability is not None:
        availability.append(_availability(collector_availability))
    payload: dict[str, Any] = {
        "platform": platform,
        "name": name,
        "unique_id": key,
        "default_entity_id": entity_id,
        "state_topic": state_topic,
        "value_template": value_template,
        "availability": availability,
        "availability_mode": "all",
    }
    if diagnostic:
        payload["entity_category"] = "diagnostic"
    payload.update(extra)
    return payload


def build_discovery_payload(
    config: AppConfig,
    build: BuildInfo,
) -> dict[str, Any]:
    topics = build_topics(config)
    prefix = entity_prefix(config.general.instance_id)

    def uid(component: str) -> str:
        return f"{topics.device_id}_{component}"

    def sensor(
        component: str,
        name: str,
        field: str,
        *,
        diagnostic: bool = False,
        collector: bool = True,
        entity_suffix: str | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        suffix = entity_suffix or component
        return _component(
            platform="sensor",
            name=name,
            key=uid(component),
            entity_id=f"sensor.{prefix}_{suffix}",
            state_topic=topics.state,
            value_template=f"{{{{ value_json.{field} }}}}",
            app_availability=topics.app_availability,
            collector_availability=(
                topics.collector_availability if collector else None
            ),
            diagnostic=diagnostic,
            **extra,
        )

    def binary(
        component: str,
        name: str,
        field: str,
        icon: str,
    ) -> dict[str, Any]:
        return _component(
            platform="binary_sensor",
            name=name,
            key=uid(component),
            entity_id=f"binary_sensor.{prefix}_{component}",
            state_topic=topics.state,
            value_template=(
                f"{{{{ 'ON' if value_json.{field} else 'OFF' }}}}"
            ),
            app_availability=topics.app_availability,
            collector_availability=topics.collector_availability,
            icon=icon,
        )

    cpu_extra = {
        "state_class": "measurement",
        "unit_of_measurement": "%",
        "suggested_display_precision": 1,
    }

    components: dict[str, Any] = {
        "activity": sensor(
            "activity", "Plex activity", "activity", collector=True,
            icon="mdi:plex",
        ),
        "current_item": sensor(
            "current_item", "Plex current item", "current_item",
            diagnostic=True,
            icon="mdi:movie-open",
            json_attributes_topic=topics.state,
            json_attributes_template=(
                "{{ dict("
                "count=value_json.current_item_count, "
                "items=value_json.current_items, "
                "transcoder_count=value_json.transcoder_count, "
                "scanner_count=value_json.scanner_count"
                ") | tojson }}"
            ),
        ),
        "server_running": binary(
            "server_running", "Plex server running", "server_running",
            "mdi:server",
        ),
        "scanner_running": binary(
            "scanner_running", "Plex scanner running", "scanner_running",
            "mdi:magnify-scan",
        ),
        "credits_detection": binary(
            "credits_detection", "Plex credits detection", "credits_detection",
            "mdi:movie-roll",
        ),
        "intro_detection": binary(
            "intro_detection", "Plex intro detection", "intro_detection",
            "mdi:movie-filter",
        ),
        "thumbnail_generation": binary(
            "thumbnail_generation", "Plex thumbnail generation",
            "thumbnail_generation", "mdi:image-multiple",
        ),
        "transcoder_running": binary(
            "transcoder_running", "Plex transcoder running",
            "transcoder_running", "mdi:movie-cog",
        ),
        "transcoder_count": sensor(
            "transcoder_count", "Plex transcoder count",
            "transcoder_count", icon="mdi:movie-cog",
        ),
        "cpu": sensor(
            "cpu", "Plex CPU", "cpu", icon="mdi:cpu-64-bit", **cpu_extra
        ),
        "cpu_avg": sensor(
            "cpu_avg", "Plex CPU 1m average", "cpu_avg",
            icon="mdi:chart-line", **cpu_extra
        ),
        "cpu_max": sensor(
            "cpu_max", "Plex CPU 1m maximum", "cpu_max",
            icon="mdi:chart-bell-curve-cumulative", **cpu_extra
        ),
        "scanner_cpu": sensor(
            "scanner_cpu", "Plex scanner CPU", "scanner_cpu",
            icon="mdi:cpu-64-bit", **cpu_extra
        ),
        "scanner_cpu_avg": sensor(
            "scanner_cpu_avg", "Plex scanner CPU 1m average", "scanner_cpu_avg",
            icon="mdi:chart-line", **cpu_extra
        ),
        "scanner_cpu_max": sensor(
            "scanner_cpu_max", "Plex scanner CPU 1m maximum", "scanner_cpu_max",
            icon="mdi:chart-bell-curve-cumulative", **cpu_extra
        ),
        "transcoder_cpu": sensor(
            "transcoder_cpu", "Plex transcoder CPU", "transcoder_cpu",
            icon="mdi:cpu-64-bit", **cpu_extra
        ),
        "transcoder_cpu_avg": sensor(
            "transcoder_cpu_avg", "Plex transcoder CPU 1m average",
            "transcoder_cpu_avg", icon="mdi:chart-line", **cpu_extra
        ),
        "transcoder_cpu_max": sensor(
            "transcoder_cpu_max", "Plex transcoder CPU 1m maximum",
            "transcoder_cpu_max", icon="mdi:chart-bell-curve-cumulative",
            **cpu_extra
        ),
        "scanner_actions": sensor(
            "scanner_actions", "Plex scanner actions", "scanner_actions",
            diagnostic=True, icon="mdi:format-list-bulleted",
        ),
        "process_count": sensor(
            "process_count", "Plex process count", "process_count",
            diagnostic=True, icon="mdi:counter",
        ),
        "collector_status": sensor(
            "collector_status", "Plex collector status", "collector_status",
            diagnostic=True, collector=False, icon="mdi:database-check",
        ),
        "last_refresh": sensor(
            "last_refresh", "Plex last refresh", "last_refresh",
            diagnostic=True, collector=True, device_class="timestamp",
            icon="mdi:refresh",
        ),
    }

    components["build"] = _component(
        platform="sensor",
        name="Plex build",
        key=uid("build"),
        entity_id=f"sensor.{prefix}_build",
        state_topic=topics.state,
        value_template="{{ value_json.build_commit_short }}",
        app_availability=topics.app_availability,
        collector_availability=None,
        diagnostic=True,
        icon="mdi:source-commit",
        json_attributes_topic=topics.state,
        json_attributes_template=(
            "{{ {'version': value_json.build_version, "
            "'source': value_json.build_source, "
            "'commit': value_json.build_commit} | tojson }}"
        ),
    )

    components["refresh"] = {
        "platform": "button",
        "name": "Plex refresh",
        "unique_id": uid("refresh"),
        "default_entity_id": f"button.{prefix}_refresh",
        "command_topic": topics.refresh,
        "payload_press": "PRESS",
        "availability": [_availability(topics.app_availability)],
        "availability_mode": "all",
        "entity_category": "diagnostic",
        "icon": "mdi:refresh",
    }

    return {
        "device": {
            "identifiers": [topics.device_id],
            "name": config.general.instance_name,
            "manufacturer": "DigitalHouses",
            "model": "Linux Plex Workload Monitor",
            "sw_version": build.version,
        },
        "origin": {
            "name": "DigitalHouses Plex Monitoring",
            "sw_version": build.version,
            "support_url": (
                "https://github.com/DigitalHouses/home-assistant-apps/"
                "tree/main/digitalhouses_plex_monitoring"
            ),
        },
        "components": components,
    }
