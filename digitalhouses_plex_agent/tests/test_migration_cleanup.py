from pathlib import Path

from app.config import load_config
from app.migration_cleanup import (
    legacy_base_topic,
    legacy_discovery_topic,
)


def _config(tmp_path: Path, *, instance: str = "plex"):
    path = tmp_path / "legacy.conf"
    path.write_text(
        "[general]\n"
        f"instance_id = {instance}\n"
        "[mqtt]\n"
        "host = mqtt.example\n"
        "topic_prefix = DigitalHouses/Global/plex_monitoring\n",
        encoding="utf-8",
    )
    return load_config(path)


def test_legacy_default_instance_base_is_flat(tmp_path: Path):
    config = _config(tmp_path)
    assert legacy_base_topic(config) == "DigitalHouses/Global/plex_monitoring"
    assert legacy_discovery_topic(config) == (
        "homeassistant/device/digitalhouses_plex_monitoring_plex/config"
    )


def test_legacy_secondary_instance_keeps_instance_segment(tmp_path: Path):
    config = _config(tmp_path, instance="plex_guest")
    assert legacy_base_topic(config) == (
        "DigitalHouses/Global/plex_monitoring/plex_guest"
    )
    assert legacy_discovery_topic(config) == (
        "homeassistant/device/digitalhouses_plex_monitoring_plex_guest/config"
    )
