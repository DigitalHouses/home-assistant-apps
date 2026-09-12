import app.main as main_module
from app.config import MqttConfig, UpsConfig
from app.identity import HostIdentity
from app.topics import build_ups_topics
from app.ups_nut import parse_upsc_output


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


def _ups(*, policy_apply_enabled: bool):
    return UpsConfig(
        enabled=True,
        name="ups",
        host="127.0.0.1",
        port=3493,
        poll_interval_seconds=5.0,
        command_timeout_seconds=3.0,
        policy_apply_enabled=policy_apply_enabled,
    )


def test_local_gate_blocks_policy_writer_construction_when_disabled():
    assert hasattr(main_module, "build_ups_policy_applier")
    factory_calls = []

    result = main_module.build_ups_policy_applier(
        _ups(policy_apply_enabled=False),
        applier_factory=lambda **kwargs: factory_calls.append(kwargs),
        ups_reader=lambda config: (_ for _ in ()).throw(AssertionError("must not read UPS")),
    )

    assert result is None
    assert factory_calls == []


def test_local_gate_builds_policy_writer_only_when_explicitly_enabled():
    assert hasattr(main_module, "build_ups_policy_applier")
    captured = {}

    class FakeApplier:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def apply(self, draft, facts):
            return draft, facts

    snapshot = parse_upsc_output("ups.delay.start: 180\nups.status: OL\n")
    writer = main_module.build_ups_policy_applier(
        _ups(policy_apply_enabled=True),
        applier_factory=FakeApplier,
        ups_reader=lambda config: snapshot,
    )

    assert callable(writer)
    assert captured["ups_name"] == "ups"
    assert captured["effective_restart_delay_reader"]() == 180


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
