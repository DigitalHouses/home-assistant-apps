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


def test_ups_defaults_to_disabled_for_existing_config(tmp_path: Path):
    path = write_config(tmp_path, "[mqtt]\nhost = broker\n")
    config = load_config(path)
    assert config.ups.enabled is False
    assert config.ups.name == "ups"
    assert config.ups.host == "127.0.0.1"
    assert config.ups.port == 3493
    assert config.ups.poll_interval_seconds == 5.0
    assert config.ups.command_timeout_seconds == 3.0
    assert config.ups.policy_apply_enabled is False


def test_ups_section_is_parsed(tmp_path: Path):
    path = write_config(
        tmp_path,
        """[mqtt]
host = broker
[ups]
enabled = true
name = rackups
host = 127.0.0.1
port = 3493
poll_interval_seconds = 7
command_timeout_seconds = 2
policy_apply_enabled = true
""",
    )
    config = load_config(path)
    assert config.ups.enabled is True
    assert config.ups.name == "rackups"
    assert config.ups.host == "127.0.0.1"
    assert config.ups.port == 3493
    assert config.ups.poll_interval_seconds == 7.0
    assert config.ups.command_timeout_seconds == 2.0
    assert config.ups.policy_apply_enabled is True


def test_ups_config_validation(tmp_path: Path):
    bad = write_config(
        tmp_path,
        """[mqtt]
host = broker
[ups]
enabled = maybe
""",
    )
    with pytest.raises(ConfigError, match="ups.enabled"):
        load_config(bad)


def test_ups_policy_apply_gate_requires_boolean(tmp_path: Path):
    bad = write_config(
        tmp_path,
        """[mqtt]
host = broker
[ups]
policy_apply_enabled = maybe
""",
    )
    with pytest.raises(ConfigError, match="ups.policy_apply_enabled"):
        load_config(bad)
