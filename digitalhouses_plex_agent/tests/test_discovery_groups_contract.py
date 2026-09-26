from pathlib import Path
from tempfile import TemporaryDirectory

from app.config import load_config
from app.discovery import build_discovery_payload, build_topics, state_group_topic
from app.models import BuildInfo
from app.plex_api import LibraryInfo


def config():
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "app.conf"
        path.write_text("[mqtt]\nhost = mqtt\n", encoding="utf-8")
        return load_config(path)

def test_existing_entities_are_routed_to_semantic_state_groups():
    cfg = config()
    topics = build_topics(cfg)
    components = build_discovery_payload(
        cfg,
        BuildInfo("0.3.0", "digitalhouses_plex_agent-v0.3.0", "abcdef"),
    )["components"]

    assert components["activity"]["state_topic"] == state_group_topic(topics, "activity")
    assert components["current_item"]["state_topic"] == state_group_topic(topics, "activity")
    assert components["cpu"]["state_topic"] == state_group_topic(topics, "cpu")
    assert components["playback_count"]["state_topic"] == state_group_topic(topics, "playback")
    assert components["playback_started_at"]["state_topic"] == state_group_topic(topics, "playback")
    assert components["libraries"]["state_topic"] == state_group_topic(topics, "libraries")
    assert components["collector_status"]["state_topic"] == state_group_topic(topics, "diagnostics")
    assert components["api_status"]["state_topic"] == state_group_topic(topics, "diagnostics")


def test_discovery_exposes_agent_diagnostics_without_commit_sensor():
    cfg = config()
    topics = build_topics(cfg)
    components = build_discovery_payload(
        cfg,
        BuildInfo("0.3.0", "digitalhouses_plex_agent-v0.3.0", "abcdef"),
    )["components"]
    diagnostics = state_group_topic(topics, "diagnostics")

    assert "build" not in components

    assert components["agent_version"]["default_entity_id"] == "sensor.dh_plex_agent_version"
    assert components["agent_version"]["state_topic"] == diagnostics
    assert components["agent_version"]["entity_category"] == "diagnostic"

    assert components["agent_uptime"]["default_entity_id"] == "sensor.dh_plex_agent_uptime"
    assert components["agent_uptime"]["state_topic"] == diagnostics
    assert components["agent_uptime"]["device_class"] == "duration"
    assert components["agent_uptime"]["unit_of_measurement"] == "s"

    assert components["agent_started_at"]["default_entity_id"] == (
        "sensor.dh_plex_agent_started_at"
    )
    assert components["agent_started_at"]["state_topic"] == diagnostics
    assert components["agent_started_at"]["device_class"] == "timestamp"

    assert components["playback_started_at"]["default_entity_id"] == (
        "sensor.dh_plex_agent_playback_started_at"
    )
    assert components["playback_started_at"]["device_class"] == "timestamp"

    assert components["publication_profile"]["default_entity_id"] == (
        "sensor.dh_plex_agent_publication_profile"
    )
    assert components["last_publication"]["default_entity_id"] == (
        "sensor.dh_plex_agent_last_publication"
    )


def test_dynamic_library_entities_use_libraries_group():
    cfg = config()
    topics = build_topics(cfg)
    library = LibraryInfo(
        section_id="3",
        title="Music",
        library_type="artist",
        content_type="audio",
        item_count=160,
        artists=3,
        albums=20,
        tracks=160,
    )
    components = build_discovery_payload(
        cfg,
        BuildInfo("0.3.0", "digitalhouses_plex_agent-v0.3.0", "abcdef"),
        (library,),
    )["components"]

    assert components["library_3"]["state_topic"] == state_group_topic(topics, "libraries")
