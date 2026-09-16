from app.config import MqttConfig
from app.identity import HostIdentity
from app.shutdown_discovery import build_shutdown_aware_ups_discovery_payload
from app.topics import build_ups_topics, ups_state_group_topic
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


def _payload():
    snapshot = parse_upsc_output(
        "device.mfr: CPS\n"
        "device.model: UT2200E\n"
        "device.serial: TEST123\n"
        "ups.status: OL\n"
        "battery.charge: 100\n"
        "battery.runtime: 2160\n"
        "ups.load: 5\n"
    )
    return build_shutdown_aware_ups_discovery_payload(
        _mqtt(),
        _identity(),
        version="0.3.0",
        snapshot=snapshot,
        capabilities=None,
        shutdown_policy=None,
    )


def test_canonical_ups_device_identity_and_migration_discovery_topics():
    topics = build_ups_topics(_mqtt(), _identity())
    payload = _payload()

    assert topics.base == "DigitalHouses/Global/dh_pve_app/node_a/ups"
    assert topics.device_id == "dh_app_pve_ups_node_a"
    assert topics.discovery == "homeassistant/device/dh_app_pve_ups_node_a/config"
    assert topics.legacy_discoveries == (
        "homeassistant/device/dh_pve_ups_node_a/config",
        "homeassistant/device/dh_ups_node_a/config",
    )
    assert payload["device"]["identifiers"] == ["dh_app_pve_ups_node_a"]
    assert all(
        component["unique_id"].startswith("dh_app_pve_ups_node_a_")
        for component in payload["components"].values()
        if "unique_id" in component
    )


def test_canonical_ups_public_entity_ids_are_consistent():
    c = _payload()["components"]

    assert c["status"]["default_entity_id"] == "sensor.dh_app_pve_ups_status"
    assert c["battery_charge"]["default_entity_id"] == "sensor.dh_app_pve_ups_battery_charge"
    assert c["refresh"]["default_entity_id"] == "button.dh_app_pve_ups_refresh"
    assert c["guest_shutdown_budget"]["default_entity_id"] == (
        "sensor.dh_app_pve_ups_guest_shutdown_budget"
    )
    assert c["shutdown_readiness"]["default_entity_id"] == (
        "sensor.dh_app_pve_ups_shutdown_readiness"
    )
    assert c["ups_app_profile"]["default_entity_id"] == "sensor.dh_app_pve_ups_app_profile"
    assert c["ups_last_publication"]["default_entity_id"] == (
        "sensor.dh_app_pve_ups_last_publication"
    )

    assert not any(
        ".dh_pve_ups_" in component.get("default_entity_id", "")
        or ".dh_ups_" in component.get("default_entity_id", "")
        for component in c.values()
    )


def test_ups_problem_binaries_use_app_owned_retained_topics():
    topics = build_ups_topics(_mqtt(), _identity())
    c = _payload()["components"]
    expected = (
        "nut_unavailable",
        "on_battery",
        "low_battery",
        "overload",
        "replace_battery",
        "bypass",
        "power_state_unknown",
    )

    for problem_id in expected:
        component = c[f"{problem_id}_problem"]
        assert component["platform"] == "binary_sensor"
        assert component["default_entity_id"] == (
            f"binary_sensor.dh_app_pve_ups_{problem_id}_problem"
        )
        assert component["state_topic"] == (
            f"{topics.base}/problems/{problem_id}/state"
        )
        assert component["payload_on"] == "ON"
        assert component["payload_off"] == "OFF"
        assert component["device_class"] == "problem"
        assert component["entity_category"] == "diagnostic"
        assert component["availability"] == [
            {
                "topic": topics.availability,
                "payload_available": "online",
                "payload_not_available": "offline",
            }
        ]


def test_ups_problem_aggregate_and_native_event_are_canonical():
    topics = build_ups_topics(_mqtt(), _identity())
    c = _payload()["components"]

    aggregate = c["problems"]
    assert aggregate["platform"] == "sensor"
    assert aggregate["default_entity_id"] == "sensor.dh_app_pve_ups_problems"
    assert aggregate["state_topic"] == f"{topics.base}/problems/aggregate"
    assert aggregate["json_attributes_topic"] == f"{topics.base}/problems/presentation"
    assert aggregate["entity_category"] == "diagnostic"

    event = c["diagnostic_event"]
    assert event["platform"] == "event"
    assert event["default_entity_id"] == "event.dh_app_pve_ups_diagnostic"
    assert event["state_topic"] == topics.diagnostic_event
    assert event["event_types"] == [
        "problem_started",
        "problem_recovered",
        "problem_updated",
        "config_changed",
    ]
    assert event["qos"] == 1
    assert event["entity_category"] == "diagnostic"
    assert "json_attributes_topic" not in event


def test_line_power_monthly_discovery_is_canonical_and_grouped():
    topics = build_ups_topics(_mqtt(), _identity())
    c = _payload()["components"]
    state_topic = ups_state_group_topic(topics, "line_power_statistics")

    expected_ids = {
        "line_power": "binary_sensor.dh_app_pve_ups_line_power",
        "line_power_online_month": "sensor.dh_app_pve_ups_line_power_online_month",
        "line_power_offline_month": "sensor.dh_app_pve_ups_line_power_offline_month",
        "line_power_outages_month": "sensor.dh_app_pve_ups_line_power_outages_month",
        "line_power_availability_month": "sensor.dh_app_pve_ups_line_power_availability_month",
        "line_power_current_outage_started": (
            "sensor.dh_app_pve_ups_line_power_current_outage_started"
        ),
        "line_power_last_failure": "sensor.dh_app_pve_ups_line_power_last_failure",
        "line_power_last_restore": "sensor.dh_app_pve_ups_line_power_last_restore",
        "line_power_last_outage_duration": (
            "sensor.dh_app_pve_ups_line_power_last_outage_duration"
        ),
    }

    for key, entity_id in expected_ids.items():
        assert c[key]["default_entity_id"] == entity_id
        assert c[key]["state_topic"] == state_topic

    assert c["line_power"]["platform"] == "binary_sensor"
    assert c["line_power_online_month"]["unit_of_measurement"] == "s"
    assert c["line_power_online_month"]["device_class"] == "duration"
    assert c["line_power_offline_month"]["unit_of_measurement"] == "s"
    assert c["line_power_offline_month"]["device_class"] == "duration"
    assert c["line_power_availability_month"]["unit_of_measurement"] == "%"
    assert c["line_power_current_outage_started"]["device_class"] == "timestamp"
    assert c["line_power_last_failure"]["device_class"] == "timestamp"
    assert c["line_power_last_restore"]["device_class"] == "timestamp"
    assert c["line_power_last_outage_duration"]["unit_of_measurement"] == "s"
    assert c["line_power_last_outage_duration"]["device_class"] == "duration"

    metadata = c["line_power_availability_month"]["json_attributes_template"]
    assert "month_key" in metadata
    assert "month_label_ru" in metadata
    assert "tracking_since" in metadata
    assert "partial_month" in metadata
