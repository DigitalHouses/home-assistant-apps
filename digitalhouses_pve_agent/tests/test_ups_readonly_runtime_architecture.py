from pathlib import Path

from app.config import MqttConfig, load_config
from app.discovery_ups import build_ups_discovery_payload
from app.identity import HostIdentity
from app.mqtt_bridge import MqttEvents
from app.runtime_settings import RuntimeSettings
from app.topics import build_topics, build_ups_topics
from app.ups_shutdown_policy import parse_shutdown_policy


def _mqtt():
    return MqttConfig(
        host="mqtt",
        port=1883,
        username="",
        password="",
        topic_prefix="DigitalHouses/Global/digitalhouses_pve_agent",
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
    unit = Path("digitalhouses_pve_agent/systemd/digitalhouses_pve_agent.service").read_text(encoding="utf-8")

    assert "ProtectSystem=full" in unit
    assert "ReadWritePaths=/etc/nut" not in unit


def test_legacy_policy_apply_enabled_config_is_ignored(tmp_path):
    path = tmp_path / "digitalhouses_pve_agent.conf"
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


def test_legacy_nut_timer_is_observed_read_only_when_present():
    policy = parse_shutdown_policy(
        """MONITOR ups@127.0.0.1 1 user password primary
SHUTDOWNCMD \"/sbin/shutdown -h now\"
""",
        """CMDSCRIPT /opt/digitalhouses/digitalhouses_pve_agent/bin/digitalhouses-pve-agent-ups-policy-cmd
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


def test_main_has_no_legacy_timer_commissioning_writer_surface():
    text = Path("digitalhouses_pve_agent/app/main.py").read_text(encoding="utf-8")

    assert "ups_commission" not in text
    assert '"--ups-policy-commission"' not in text
    assert '"--on-battery-delay-minutes"' not in text
    assert '"--power-restore-delay-seconds"' not in text
    assert "policy_applier=build_ups_policy_applier" not in text
