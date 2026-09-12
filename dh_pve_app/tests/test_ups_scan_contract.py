import subprocess

from app.config import AppConfig, GeneralConfig, MqttConfig, UpsConfig
from app.discovery import build_discovery_payload
from app.discovery_ups import build_ups_discovery_payload
from app.identity import HostIdentity
from app.mqtt_bridge import MqttEvents
from app.runtime_settings import RuntimeSettings
from app.topics import build_topics, build_ups_topics
from app.ups_nut import parse_upsc_output
import app.ups_nut as ups_nut


def _mqtt() -> MqttConfig:
    return MqttConfig(
        host="mqtt",
        port=1883,
        username="",
        password="",
        topic_prefix="DigitalHouses/Global/dh_pve_app",
        discovery_prefix="homeassistant",
        keepalive_seconds=60,
    )


def _identity() -> HostIdentity:
    return HostIdentity(
        machine_id="0123456789abcdef0123456789abcdef",
        instance_id="node_a",
        hostname="pve",
        node_name="PVE",
    )


def _app_config() -> AppConfig:
    return AppConfig(
        general=GeneralConfig(instance_id="node_a", node_name="PVE", log_level="info"),
        mqtt=_mqtt(),
        ups=UpsConfig(enabled=False),
    )


def test_pve_device_exposes_manual_ups_scan_controls():
    topics = build_topics(_mqtt(), _identity())
    assert getattr(topics, "ups_scan", None) == topics.base + "/ups/scan"
    assert getattr(topics, "ups_scan_state", None) == topics.base + "/ups/scan/state"

    payload = build_discovery_payload(_app_config(), _identity(), version="0.2.0-alpha")
    components = payload["components"]

    assert components["ups_scan"]["default_entity_id"] == "button.dh_pve_scan_ups"
    assert components["ups_scan"]["command_topic"] == topics.ups_scan
    assert components["ups_scan_result"]["default_entity_id"] == "sensor.dh_pve_ups_scan_result"
    assert components["ups_scan_result"]["state_topic"] == topics.ups_scan_state
    assert components["ups_last_scan"]["default_entity_id"] == "sensor.dh_pve_ups_last_scan"
    assert components["ups_last_scan"]["state_topic"] == topics.ups_scan_state


def test_mqtt_events_accept_manual_ups_scan_press():
    topics = build_topics(_mqtt(), _identity())
    events = MqttEvents(topics, RuntimeSettings())

    assert hasattr(events, "ups_scan_requested")
    assert events.handle_message(topics.ups_scan, b"PRESS") is True
    assert events.ups_scan_requested.is_set()


def test_read_only_nut_scan_lists_configured_ups_names():
    assert hasattr(ups_nut, "list_ups")
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="ups\nbackup\n",
            stderr="",
        )

    names = ups_nut.list_ups(UpsConfig(enabled=False), runner=runner)

    assert names == ("ups", "backup")
    assert calls == [(
        ["upsc", "-l", "127.0.0.1:3493"],
        {
            "capture_output": True,
            "text": True,
            "timeout": 3.0,
            "check": True,
        },
    )]


def test_ups_device_and_entities_use_pve_scoped_public_namespace():
    topics = build_ups_topics(_mqtt(), _identity())
    assert topics.device_id == "dh_pve_ups_node_a"
    assert topics.discovery == "homeassistant/device/dh_pve_ups_node_a/config"
    assert getattr(topics, "legacy_discovery", None) == "homeassistant/device/dh_ups_node_a/config"

    snapshot = parse_upsc_output(
        "device.mfr: CPS\n"
        "device.model: Demo UPS\n"
        "device.serial: SERIAL1\n"
        "ups.status: OL\n"
        "battery.charge: 100\n"
    )
    payload = build_ups_discovery_payload(
        _mqtt(), _identity(), version="0.2.0-alpha", snapshot=snapshot
    )

    assert payload["device"]["name"] == "DH PVE UPS"
    assert payload["device"]["identifiers"] == ["dh_pve_ups_node_a"]
    assert payload["components"]["status"]["default_entity_id"] == "sensor.dh_pve_ups_status"
    assert payload["components"]["battery_charge"]["default_entity_id"] == "sensor.dh_pve_ups_battery_charge"
    assert payload["components"]["refresh"]["default_entity_id"] == "button.dh_pve_ups_refresh"
