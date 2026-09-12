from pathlib import Path

from app.config import MqttConfig
from app.identity import HostIdentity
from app.topics import build_ups_topics


def _mqtt():
    return MqttConfig(
        host="mqtt",
        port=1883,
        username="",
        password="",
        topic_prefix="DigitalHouses/Global/dh_pve_app",
        discovery_prefix="homeassistant",
        keepalive_seconds=60,
    )


def _identity():
    return HostIdentity(
        machine_id="0123456789abcdef0123456789abcdef",
        instance_id="node_a",
        hostname="pve",
        node_name="PVE",
    )


def test_production_main_does_not_wire_policy_applier_before_live_commissioning():
    source = Path("dh_pve_app/app/main.py").read_text(encoding="utf-8")

    assert "UpsPolicyApplier" not in source
    assert "policy_applier=" not in source


def test_mqtt_ups_surface_has_no_shutdown_fsd_load_off_or_generic_command_topic():
    topics = build_ups_topics(_mqtt(), _identity())
    public_topics = {
        key: value
        for key, value in vars(topics).items()
        if isinstance(value, str)
    }

    forbidden_field_fragments = (
        "fsd",
        "shutdown",
        "load_off",
        "load_on",
        "upscmd",
        "command",
        "shell",
    )
    assert not {
        key
        for key in public_topics
        if any(fragment in key.casefold() for fragment in forbidden_field_fragments)
    }

    forbidden_path_fragments = (
        "/fsd",
        "/shutdown",
        "/load/off",
        "/load/on",
        "/upscmd",
        "/command",
        "/shell",
    )
    assert not {
        value
        for value in public_topics.values()
        if any(fragment in value.casefold() for fragment in forbidden_path_fragments)
    }
