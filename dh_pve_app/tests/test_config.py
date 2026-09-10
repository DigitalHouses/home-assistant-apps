from pathlib import Path

import pytest

from app.config import ConfigError, load_config


def write_config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "dh_pve_app.conf"
    path.write_text(text, encoding="utf-8")
    return path


def test_load_config_uses_expected_defaults(tmp_path: Path):
    path = write_config(tmp_path, "[mqtt]\nhost = 192.168.11.33\n")
    config = load_config(path)
    assert config.general.instance_id == ""
    assert config.general.node_name == "PVE"
    assert config.general.log_level == "info"
    assert config.mqtt.port == 1883
    assert config.mqtt.topic_prefix == "DigitalHouses/Global/dh_pve_app"
    assert config.mqtt.discovery_prefix == "homeassistant"
    assert config.mqtt.keepalive_seconds == 60


def test_load_config_requires_mqtt_host(tmp_path: Path):
    path = write_config(tmp_path, "[mqtt]\nport = 1883\n")
    with pytest.raises(ConfigError, match=r"mqtt\.host is required"):
        load_config(path)


def test_load_config_validates_explicit_instance_id(tmp_path: Path):
    path = write_config(tmp_path, "[general]\ninstance_id = Bad-ID\n[mqtt]\nhost = broker\n")
    with pytest.raises(ConfigError, match="general.instance_id"):
        load_config(path)
