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


def test_policy_discovery_is_read_only():
    components = build_ups_discovery_payload(
        _mqtt(), _identity(), version="0.2.0-alpha", snapshot=None
    )["components"]

    on_battery = components["policy_on_battery_delay_observed"]
    restore = components["policy_power_restore_delay_observed"]

    assert on_battery["platform"] == "sensor"
    assert restore["platform"] == "sensor"
    assert "command_topic" not in on_battery
    assert "command_topic" not in restore
    assert "value_json.shutdown_policy.on_battery_delay_minutes" in on_battery["value_template"]
    assert "value_json.shutdown_policy.power_restore_delay_seconds" in restore["value_template"]

    assert "policy_apply" not in components
    assert "policy_apply_result" not in components
    assert "policy_last_applied" not in components


def test_policy_mqtt_write_topics_are_ignored():
    mqtt = _mqtt()
    identity = _identity()
    pve = build_topics(mqtt, identity)
    events = MqttEvents(pve, RuntimeSettings())
    events.configure_ups(build_ups_topics(mqtt, identity))

    assert events.handle_message(
        f"{pve.base}/ups/policy/on_battery_delay/set", b"30"
    ) is False
    assert events.handle_message(
        f"{pve.base}/ups/policy/power_restore_delay/set", b"120"
    ) is False
    assert events.handle_message(
        f"{pve.base}/ups/policy/apply", b"PRESS"
    ) is False


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


def test_atomic_write_applies_parent_owner_and_group(tmp_path, monkeypatch):
    parent = tmp_path / "nut"
    parent.mkdir()
    target = parent / "upssched.conf"
    parent_stat = parent.stat()
    calls = []

    def fake_chown(path, uid, gid):
        calls.append((Path(path), uid, gid))

    monkeypatch.setattr("app.ups_policy_apply.os.chown", fake_chown)

    _atomic_write(target, b"AT ONBATT * START-TIMER x 1800\n", 0o640)

    assert calls == [(target, parent_stat.st_uid, parent_stat.st_gid)]


def test_main_exposes_explicit_commissioning_but_runtime_does_not_build_applier():
    text = Path("dh_pve_app/app/main.py").read_text(encoding="utf-8")

    assert '"--ups-policy-commission"' in text
    assert "policy_applier=build_ups_policy_applier" not in text
