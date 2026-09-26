from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from .config import AppConfig, entity_prefix
from .models import BuildInfo
from .plex_api import LibraryInfo


@dataclass(frozen=True)
class Topics:
    base: str
    state: str
    app_availability: str
    collector_availability: str
    plex_api_availability: str
    refresh: str
    discovery: str
    ha_status: str
    device_id: str


_GROUP_SEGMENT = re.compile(r"^[A-Za-z0-9_.-]+$")


def state_group_topic(topics: Topics, group: str) -> str:
    parts = group.split("/")
    if not group or any(
        not part or part in {".", ".."} or _GROUP_SEGMENT.fullmatch(part) is None
        for part in parts
    ):
        raise ValueError(f"invalid MQTT state group: {group!r}")
    return f"{topics.state}/{'/'.join(parts)}"


def build_topics(config: AppConfig) -> Topics:
    instance = config.general.instance_id
    device_id = f"digitalhouses_plex_agent_{instance}"
    topic_prefix = config.mqtt.topic_prefix.rstrip(chr(47))
    base = topic_prefix if instance == "plex" else f"{topic_prefix}/{instance}"
    return Topics(
        base=base,
        state=f"{base}/state",
        app_availability=f"{base}/availability",
        collector_availability=f"{base}/collector_availability",
        plex_api_availability=f"{base}/plex_api_availability",
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
    plex_api_availability: str | None = None,
    diagnostic: bool = False,
    **extra: Any,
) -> dict[str, Any]:
    availability = [_availability(app_availability)]
    if collector_availability is not None:
        availability.append(_availability(collector_availability))
    if plex_api_availability is not None:
        availability.append(_availability(plex_api_availability))
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


def _route_grouped_components(
    components: dict[str, Any],
    topics: Topics,
) -> None:
    groups = {
        "activity": "activity",
        "current_item": "activity",
        "server_running": "activity",
        "scanner_running": "activity",
        "credits_detection": "activity",
        "intro_detection": "activity",
        "thumbnail_generation": "activity",
        "transcoder_running": "activity",
        "transcoder_count": "activity",
        "scanner_actions": "activity",
        "cpu": "cpu",
        "scanner_cpu": "cpu",
        "transcoder_cpu": "cpu",
        "playback_count": "playback",
        "playback_started_at": "playback",
        "playback_sessions": "playback",
        "playback_active": "playback",
        "video_playback_active": "playback",
        "audio_playback_active": "playback",
        "hardware_transcode_active": "playback",
        "libraries": "libraries",
        "gpu_video": "gpu",
        "gpu_render": "gpu",
        "gpu_video_enhance": "gpu",
        "gpu_frequency": "gpu",
        "gpu_temperature": "gpu",
        "gpu_rc6": "gpu",
        "gpu_status": "gpu",
        "process_count": "diagnostics",
        "collector_status": "diagnostics",
        "api_status": "diagnostics",
        "last_refresh": "diagnostics",
        "last_boot": "diagnostics",
        "agent_version": "diagnostics",
        "agent_uptime": "diagnostics",
        "agent_started_at": "diagnostics",
        "publication_profile": "diagnostics",
        "last_publication": "diagnostics",
    }
    for key, component in components.items():
        group = "libraries" if key.startswith("library_") else groups.get(key)
        if group is None or not isinstance(component, dict):
            continue
        target = state_group_topic(topics, group)
        if component.get("state_topic") == topics.state:
            component["state_topic"] = target
        if component.get("json_attributes_topic") == topics.state:
            component["json_attributes_topic"] = target


def build_discovery_payload(
    config: AppConfig,
    build: BuildInfo,
    libraries: tuple[LibraryInfo, ...] = (),
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
        plex_api: bool = False,
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
            plex_api_availability=(
                topics.plex_api_availability if plex_api else None
            ),
            diagnostic=diagnostic,
            **extra,
        )

    def binary(
        component: str,
        name: str,
        field: str,
        icon: str,
        *,
        collector: bool = True,
        plex_api: bool = False,
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
            collector_availability=(
                topics.collector_availability if collector else None
            ),
            plex_api_availability=(
                topics.plex_api_availability if plex_api else None
            ),
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
        "scanner_cpu": sensor(
            "scanner_cpu", "Plex scanner CPU", "scanner_cpu",
            icon="mdi:cpu-64-bit", **cpu_extra
        ),
        "transcoder_cpu": sensor(
            "transcoder_cpu", "Plex transcoder CPU", "transcoder_cpu",
            icon="mdi:cpu-64-bit", **cpu_extra
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
        "playback_count": sensor(
            "playback_count", "Plex playback count", "playback_count",
            collector=False, plex_api=True, icon="mdi:play-network",
            state_class="measurement",
        ),
        "playback_started_at": sensor(
            "playback_started_at", "Plex playback started at",
            "playback_started_at", collector=False, plex_api=True,
            device_class="timestamp", icon="mdi:play-circle-outline",
        ),
        "playback_sessions": sensor(
            "playback_sessions", "Plex playback sessions",
            "playback_sessions_state", collector=False, plex_api=True,
            icon="mdi:play-box-multiple",
            json_attributes_topic=topics.state,
            json_attributes_template=(
                "{{ dict("
                "count=value_json.playback_count, "
                "video_count=value_json.video_playback_count, "
                "audio_count=value_json.audio_playback_count, "
                "sessions=value_json.playback_sessions"
                ") | tojson }}"
            ),
        ),
        "playback_active": binary(
            "playback_active", "Plex playback active", "playback_active",
            "mdi:play-circle", collector=False, plex_api=True,
        ),
        "video_playback_active": binary(
            "video_playback_active", "Plex video playback active",
            "video_playback_active", "mdi:movie-play",
            collector=False, plex_api=True,
        ),
        "audio_playback_active": binary(
            "audio_playback_active", "Plex audio playback active",
            "audio_playback_active", "mdi:music-circle",
            collector=False, plex_api=True,
        ),
        "hardware_transcode_active": binary(
            "hardware_transcode_active", "Plex hardware transcode active",
            "hardware_transcode_active", "mdi:video-check",
            collector=False, plex_api=True,
        ),
        "libraries": sensor(
            "libraries", "Plex libraries", "library_count",
            collector=False, plex_api=True, icon="mdi:folder-multiple-play",
            json_attributes_topic=topics.state,
            json_attributes_template=(
                "{{ dict(count=value_json.library_count, "
                "libraries=value_json.libraries) | tojson }}"
            ),
        ),
        "api_status": sensor(
            "api_status", "Plex API status", "plex_api_status",
            diagnostic=True, collector=False, plex_api=False,
            icon="mdi:api",
        ),
    }

    for library in libraries:
        component = f"library_{library.section_id}"
        icon = (
            "mdi:music-box-multiple"
            if library.content_type == "audio"
            else "mdi:filmstrip-box-multiple"
        )
        library_id = library.section_id.replace("'", "")
        components[component] = _component(
            platform="sensor",
            name=f"Plex library · {library.title}",
            key=uid(component),
            entity_id=f"sensor.{prefix}_{component}",
            state_topic=topics.state,
            value_template=(
                "{{ value_json.libraries_by_id['"
                + library_id
                + "'].item_count }}"
            ),
            app_availability=topics.app_availability,
            plex_api_availability=topics.plex_api_availability,
            icon=icon,
            state_class="measurement",
            json_attributes_topic=topics.state,
            json_attributes_template=(
                "{{ value_json.libraries_by_id['"
                + library_id
                + "'] | tojson }}"
            ),
        )

    gpu_topic = state_group_topic(topics, "gpu")
    gpu_metric_availability = [
        _availability(topics.app_availability),
        {
            "topic": gpu_topic,
            "value_template": (
                "{{ 'online' if value_json.available | default(false) "
                "else 'offline' }}"
            ),
            "payload_available": "online",
            "payload_not_available": "offline",
        },
    ]

    def gpu_sensor(
        component: str,
        name: str,
        field: str,
        *,
        unit: str,
        icon: str,
        device_class: str | None = None,
    ) -> dict[str, Any]:
        extra: dict[str, Any] = {
            "unit_of_measurement": unit,
            "state_class": "measurement",
            "suggested_display_precision": 1,
            "icon": icon,
            "availability": gpu_metric_availability,
        }
        if device_class is not None:
            extra["device_class"] = device_class
        return _component(
            platform="sensor",
            name=name,
            key=uid(component),
            entity_id=f"sensor.{prefix}_{component}",
            state_topic=gpu_topic,
            value_template=f"{{{{ value_json.{field} | default(none) }}}}",
            app_availability=topics.app_availability,
            diagnostic=False,
            **extra,
        )

    components["gpu_video"] = gpu_sensor(
        "gpu_video", "GPU Video", "video_busy_percent",
        unit="%", icon="mdi:video",
    )
    components["gpu_render"] = gpu_sensor(
        "gpu_render", "GPU Render", "render_busy_percent",
        unit="%", icon="mdi:gpu",
    )
    components["gpu_video_enhance"] = gpu_sensor(
        "gpu_video_enhance", "GPU Video Enhance", "video_enhance_busy_percent",
        unit="%", icon="mdi:image-filter-hdr",
    )
    components["gpu_frequency"] = gpu_sensor(
        "gpu_frequency", "GPU frequency", "frequency_mhz",
        unit="MHz", icon="mdi:speedometer",
    )
    components["gpu_temperature"] = gpu_sensor(
        "gpu_temperature", "GPU temperature", "temperature_c",
        unit="°C", icon="mdi:thermometer", device_class="temperature",
    )
    components["gpu_rc6"] = gpu_sensor(
        "gpu_rc6", "GPU RC6", "rc6_percent",
        unit="%", icon="mdi:leaf",
    )
    components["gpu_status"] = _component(
        platform="sensor",
        name="GPU status",
        key=uid("gpu_status"),
        entity_id=f"sensor.{prefix}_gpu_status",
        state_topic=gpu_topic,
        value_template="{{ value_json.status }}",
        app_availability=topics.app_availability,
        diagnostic=True,
        icon="mdi:gpu",
        json_attributes_topic=gpu_topic,
        json_attributes_template=(
            "{{ {'supported': value_json.supported, "
            "'available': value_json.available, "
            "'source': value_json.source | default(none), "
            "'pci_address': value_json.pci_address | default(none)} | tojson }}"
        ),
    )

    components["last_boot"] = _component(
        platform="sensor",
        name="Last boot",
        key=uid("last_boot"),
        entity_id=f"sensor.{prefix}_last_boot",
        state_topic=state_group_topic(topics, "diagnostics"),
        value_template="{{ value_json.server_boot_time | default(none) }}",
        app_availability=topics.app_availability,
        diagnostic=True,
        device_class="timestamp",
        icon="mdi:restart",
    )

    components["agent_version"] = _component(
        platform="sensor",
        name="Agent version",
        key=uid("agent_version"),
        entity_id=f"sensor.{prefix}_version",
        state_topic=topics.state,
        value_template="{{ value_json.agent_version }}",
        app_availability=topics.app_availability,
        diagnostic=True,
        icon="mdi:tag-outline",
    )

    components["agent_uptime"] = _component(
        platform="sensor",
        name="Agent uptime",
        key=uid("agent_uptime"),
        entity_id=f"sensor.{prefix}_uptime",
        state_topic=topics.state,
        value_template="{{ value_json.agent_uptime_seconds }}",
        app_availability=topics.app_availability,
        diagnostic=True,
        device_class="duration",
        unit_of_measurement="s",
        icon="mdi:timer-outline",
    )

    components["agent_started_at"] = _component(
        platform="sensor",
        name="Agent started at",
        key=uid("agent_started_at"),
        entity_id=f"sensor.{prefix}_started_at",
        state_topic=state_group_topic(topics, "diagnostics"),
        value_template="{{ value_json.agent_started_at }}",
        app_availability=topics.app_availability,
        diagnostic=True,
        device_class="timestamp",
        icon="mdi:clock-start",
    )

    components["publication_profile"] = _component(
        platform="sensor",
        name="Publication profile",
        key=uid("publication_profile"),
        entity_id=f"sensor.{prefix}_publication_profile",
        state_topic=topics.state,
        value_template="{{ value_json.publication_profile.state }}",
        app_availability=topics.app_availability,
        diagnostic=True,
        icon="mdi:speedometer-medium",
        json_attributes_topic=topics.state,
        json_attributes_template=(
            "{{ {'resources': value_json.publication_profile.resources, "
            "'reason': value_json.publication_profile.reason} | tojson }}"
        ),
    )

    components["last_publication"] = _component(
        platform="sensor",
        name="Last publication",
        key=uid("last_publication"),
        entity_id=f"sensor.{prefix}_last_publication",
        state_topic=topics.state,
        value_template="{{ value_json.last_publication.timestamp }}",
        app_availability=topics.app_availability,
        diagnostic=True,
        device_class="timestamp",
        icon="mdi:publish",
        json_attributes_topic=topics.state,
        json_attributes_template=(
            "{{ {'group': value_json.last_publication.group, "
            "'reason': value_json.last_publication.reason, "
            "'profile': value_json.last_publication.profile, "
            "'group_count': value_json.last_publication.group_count} | tojson }}"
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

    _route_grouped_components(components, topics)

    return {
        "device": {
            "identifiers": [topics.device_id],
            "name": config.general.instance_name,
            "manufacturer": "DigitalHouses",
            "model": "Linux Plex Workload + Playback Monitor",
            "sw_version": build.version,
        },
        "origin": {
            "name": "DigitalHouses Plex Agent",
            "sw_version": build.version,
            "support_url": (
                "https://github.com/DigitalHouses/home-assistant-apps/"
                "tree/main/digitalhouses_plex_agent"
            ),
        },
        "components": components,
    }
