from app.config import AppConfig, GeneralConfig, MqttConfig
from app.identity import HostIdentity
from app.presentation_pve import PresentationSubsystem, PvePresentationRouter
from app.shutdown_discovery import build_shutdown_aware_pve_discovery_payload


def _subsystem(data):
    return PresentationSubsystem(
        available=True,
        data=data,
        last_success="2026-09-15T00:20:00+05:00",
        error=None,
    )


def _config():
    return AppConfig(
        general=GeneralConfig(instance_id="", node_name="PVE", log_level="info"),
        mqtt=MqttConfig(
            host="mqtt",
            port=1883,
            username="",
            password="",
            topic_prefix="DigitalHouses/Global/digitalhouses_pve_agent",
            discovery_prefix="homeassistant",
            keepalive_seconds=60,
        ),
    )


def _identity():
    return HostIdentity(
        machine_id="0123456789abcdef0123456789abcdef",
        instance_id="node_a",
        hostname="pve",
        node_name="PVE",
    )


def _inventory():
    return {
        "host": {
            "hostname": "pve",
            "shutdown_history": {
                "history_count": 0,
                "history": [],
                "previous_shutdown": None,
            },
        },
        "guests": {
            "vms": {
                "110": {
                    "kind": "vm",
                    "guest_id": "110",
                    "name": "haos",
                    "status": "running",
                    "shutdown_timeout_seconds": 200,
                    "shutdown_order": 30,
                    "onboot": True,
                }
            },
            "lxcs": {
                "149": {
                    "kind": "lxc",
                    "guest_id": "149",
                    "name": "climate",
                    "status": "running",
                    "shutdown_timeout_seconds": 60,
                    "shutdown_order": 20,
                    "onboot": True,
                }
            },
            "summary": {},
        },
    }


def test_shutdown_group_contains_current_guest_shutdown_configuration():
    inventory = _inventory()
    router = PvePresentationRouter()

    publications = router.route(
        {
            "host": _subsystem(inventory["host"]),
            "guests": _subsystem(inventory["guests"]),
        },
        selected=("host", "guests"),
        now=0.0,
        collected_at="2026-09-15T00:20:00+05:00",
        last_refresh=None,
        force=True,
    )

    shutdown = next(item for item in publications if item.group == "shutdown")
    data = shutdown.payload["subsystems"]["host"]["data"]

    vm = data["guest_config"]["vms"]["110"]
    assert vm["shutdown_timeout_seconds"] == 200
    assert vm["shutdown_order"] == 30
    assert vm["onboot"] is True
    assert "last_shutdown_duration_seconds" in vm

    lxc = data["guest_config"]["lxcs"]["149"]
    assert lxc["shutdown_timeout_seconds"] == 60
    assert lxc["shutdown_order"] == 20
    assert lxc["onboot"] is True
    assert "last_shutdown_duration_seconds" in lxc


def test_shutdown_discovery_reads_current_guest_config_from_shutdown_group():
    components = build_shutdown_aware_pve_discovery_payload(
        _config(),
        _identity(),
        version="0.2.0",
        inventory=_inventory(),
    )["components"]

    attrs = components["vm_110_shutdown"]["json_attributes_template"]

    assert "value_json.subsystems.host.data.guest_config.vms" in attrs
    assert "value_json.subsystems.guests.data" not in attrs


def test_shutdown_discovery_reads_latest_guest_fact_from_shutdown_group():
    components = build_shutdown_aware_pve_discovery_payload(
        _config(),
        _identity(),
        version="0.2.0",
        inventory=_inventory(),
    )["components"]

    for component_id, plural, guest_id in (
        ("vm_110_shutdown", "vms", "110"),
        ("lxc_149_shutdown", "lxcs", "149"),
    ):
        component = components[component_id]
        templates = (
            component["value_template"],
            component["json_attributes_template"],
        )
        expected_path = (
            f'value_json.subsystems.host.data.guest_config.{plural}["{guest_id}"]'
        )

        for template in templates:
            assert expected_path in template
            assert "previous_shutdown.guests" not in template

        attrs = component["json_attributes_template"]
        assert "last_shutdown_duration_seconds" in attrs
        assert "last_shutdown_timeout_seconds" in attrs
        assert "last_shutdown_timeout_ratio" in attrs
        assert "last_shutdown_assessment" in attrs
        assert "next_shutdown_timeout_seconds" in attrs
        assert "next_shutdown_timeout_ratio" in attrs
        assert "next_shutdown_assessment" in attrs
        assert "current_timeout_seconds" not in attrs
        assert "current_timeout_ratio" not in attrs
        assert "current_assessment" not in attrs
        assert "last_shutdown_source" in attrs


def test_guest_status_discovery_exposes_autostart_without_extra_entity():
    components = build_shutdown_aware_pve_discovery_payload(
        _config(),
        _identity(),
        version="0.2.0",
        inventory=_inventory(),
    )["components"]

    attrs = components["vm_110_status"]["json_attributes_template"]

    assert "onboot" in attrs
    assert "last_shutdown_assessment" in attrs
