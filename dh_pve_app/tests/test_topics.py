from pathlib import Path

import pytest

from app.config import GeneralConfig, MqttConfig
from app.identity import HostIdentity, IdentityError, normalize_machine_id, resolve_identity
from app.topics import build_topics


def test_normalize_machine_id_accepts_uuid_style_and_normalizes():
    assert normalize_machine_id("AB31A377-8F59-49AD-8648-BDDACCA0715C\n") == "ab31a3778f5949ad8648bddacca0715c"


def test_normalize_machine_id_rejects_invalid_value():
    with pytest.raises(IdentityError):
        normalize_machine_id("not-a-machine-id")


def test_resolve_identity_uses_machine_id_when_instance_is_blank(tmp_path: Path):
    machine_id = tmp_path / "machine-id"
    machine_id.write_text("ab31a3778f5949ad8648bddacca0715c\n", encoding="utf-8")
    general = GeneralConfig(instance_id="", node_name="PVE", log_level="info")
    identity = resolve_identity(general, machine_id_path=machine_id, hostname="pve")
    assert identity.machine_id == "ab31a3778f5949ad8648bddacca0715c"
    assert identity.instance_id == "ab31a3778f5949ad8648bddacca0715c"
    assert identity.hostname == "pve"


def test_build_topics_is_exact():
    mqtt = MqttConfig(
        host="broker",
        port=1883,
        username="",
        password="",
        topic_prefix="DigitalHouses/Global/dh_pve_app",
        discovery_prefix="homeassistant",
        keepalive_seconds=60,
    )
    identity = HostIdentity(
        machine_id="ab31a3778f5949ad8648bddacca0715c",
        instance_id="shahristan",
        hostname="pve",
        node_name="PVE",
    )
    topics = build_topics(mqtt, identity)
    assert topics.base == "DigitalHouses/Global/dh_pve_app/shahristan"
    assert topics.state == topics.base + "/state"
    assert topics.availability == topics.base + "/availability"
    assert topics.refresh == topics.base + "/refresh"
    assert topics.manifest == topics.base + "/manifest"
    assert topics.settings_prefix == topics.base + "/settings"
    assert topics.device_id == "dh_pve_shahristan"
    assert topics.discovery == "homeassistant/device/dh_pve_shahristan/config"
    assert topics.ha_status == "homeassistant/status"
