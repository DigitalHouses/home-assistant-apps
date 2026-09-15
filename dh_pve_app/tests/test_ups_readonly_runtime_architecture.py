from pathlib import Path

from app.config import MqttConfig, load_config
from app.discovery_ups import build_ups_discovery_payload
from app.identity import HostIdentity
from app.mqtt_bridge import MqttEvents
from app.runtime_settings import RuntimeSettings
from app.topics import build_topics, build_ups_topics
from app.ups_policy_apply import _atomic_write
from app.ups_shutdown_policy import parse_shutdown_policy


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


def test_policy_discovery_exposes_only_app_owned_v2_write_controls():
    components = build_ups_discovery_payload(
        _mqtt(), _identity(), version="0.2.0-alpha", snapshot=None
    )["components"]

    on_battery = components["policy_on_battery_delay_observed"]
    restore = components["policy_power_restore_delay_observed"]
    charge = components["policy_charge_threshold"]
    reserve = components["policy_runtime_reserve"]
    apply = components["policy_apply"]

    assert on_battery["platform"] == "sensor"
    assert restore["platform"] == "sensor"
    assert "command_topic" not in on_battery
    assert "command_topic" not in restore
    assert charge["platform"] == "number"
    assert reserve["platform"] == "number"
    assert apply["platform"] == "button"


def test_legacy_policy_write_topics_are_ignored_but_v2_apply_is_explicit():
    mqtt = _mqtt()
    identity = _identity()
    pve = build_topics(mqtt, identity)
    ups = build_ups_topics(mqtt, identity)
    events = MqttEvents(pve, RuntimeSettings())
    events.configure_ups(ups)

    assert events.handle_message(
        f"{pve.base}/ups/policy/on_battery_delay/set", b"30"
    ) is False
    assert events.handle_message(
        f"{pve.base}/ups/policy/power_restore_delay/set", b"120"
    ) is False
    assert events.handle_message(ups.policy_apply, b"NO") is False
    assert events.handle_message(ups.policy_apply, b"PRESS") is True
    assert events.ups_policy_apply_requested.is_set()


def test_runtime_service_cannot_write_etc_nut():
    unit = Path("dh_pve_app/systemd/dh_pve_app.service").read_text(encoding="utf-8")

    assert "ProtectSystem=full" in unit
    assert "ReadWritePaths=/etc/nut" not in unit


def test_legacy_policy_apply_enabled_config_is_ignored(tmp_path):
    path = tmp_path / "dh_pve_app.conf"
    path.write_text(
        """[mqtt]
host = broker
[ups]
policy_apply_enabled = true
""",
        encoding="utf-8",
    )

    config = load_config(path)

    assert not hasattr(config.ups, "policy_apply_enabled")


def test_effective_policy_delays_are_parsed_from_nut_files():
    policy = parse_shutdown_policy(
        """MONITOR ups@127.0.0.1 1 user password primary
SHUTDOWNCMD \"/sbin/shutdown -h now\"
""",
        """CMDSCRIPT /opt/digitalhouses/dh_pve_app/bin/dh-pve-ups-policy-cmd
AT ONBATT * START-TIMER dh-pve-ups-shutdown 1800
AT ONLINE * CANCEL-TIMER dh-pve-ups-shutdown
""",
        ups_conf_text="""[ups]
driver = usbhid-ups
ondelay = 120
offdelay = 60
""",
        ups_name="ups",
        monitor_active=True,
        guest_shutdown_budget_seconds=280,
    )

    assert policy.on_battery_delay_minutes == 30
    assert policy.power_restore_delay_seconds == 120
    assert policy.guest_shutdown_budget_seconds == 280


def test_atomic_write_sets_parent_owner_before_replace(tmp_path, monkeypatch):
    parent = tmp_path / "nut"
    parent.mkdir()
    target = parent / "upssched.conf"
    parent_stat = parent.stat()
    chowns = []
    replaces = []
    real_replace = __import__("os").replace

    def fake_chown(path, uid, gid):
        chowns.append((Path(path), uid, gid))

    def tracked_replace(source, destination):
        replaces.append((Path(source), Path(destination)))
        assert chowns
        assert chowns[-1][0] == Path(source)
        return real_replace(source, destination)

    monkeypatch.setattr("app.ups_policy_apply.os.chown", fake_chown)
    monkeypatch.setattr("app.ups_policy_apply.os.replace", tracked_replace)

    _atomic_write(target, b"AT ONBATT * START-TIMER x 1800\n", 0o640)

    assert len(chowns) == 1
    temp, uid, gid = chowns[0]
    assert temp.parent == parent
    assert temp != target
    assert uid == parent_stat.st_uid
    assert gid == parent_stat.st_gid
    assert replaces == [(temp, target)]


def test_main_exposes_explicit_commissioning_but_runtime_does_not_build_applier():
    text = Path("dh_pve_app/app/main.py").read_text(encoding="utf-8")

    assert '"--ups-policy-commission"' in text
    assert "policy_applier=build_ups_policy_applier" not in text
