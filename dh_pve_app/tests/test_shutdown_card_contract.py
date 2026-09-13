from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CARD = ROOT / "examples" / "dh_pve_shutdown_readiness_card.yaml"


def _text() -> str:
    return CARD.read_text(encoding="utf-8")


def test_shutdown_readiness_card_exists_and_uses_backend_entities():
    assert CARD.is_file()
    text = _text()
    for entity_id in (
        "sensor.dh_pve_previous_shutdown",
        "sensor.dh_pve_shutdown_history",
        "sensor.dh_pve_ups_shutdown_readiness",
        "sensor.dh_pve_ups_guest_shutdown_budget",
    ):
        assert entity_id in text


def test_shutdown_readiness_card_hides_ups_summary_when_ups_is_absent():
    text = _text()
    assert "sensor.dh_pve_ups_shutdown_readiness" in text
    assert "not in ['unknown', 'unavailable', 'none', '']" in text
    assert "shutdown_readiness.status" not in text


def test_shutdown_readiness_card_colors_guest_shutdown_results_from_backend_facts():
    text = _text()
    assert "proxmox_metric') == 'shutdown_duration'" in text
    for attribute in (
        "shutdown_timeout_seconds",
        "last_shutdown_duration_seconds",
        "last_shutdown_timeout_seconds",
        "last_shutdown_timeout_ratio",
        "last_shutdown_result",
        "last_shutdown_forced",
    ):
        assert attribute in text
    assert "result in ['timeout', 'forced']" in text
    assert "ratio >= 0.8" in text
    assert "color = 'red'" in text
    assert "color = 'orange'" in text
    assert "color = 'green'" in text
    assert "color = 'grey'" in text


def test_shutdown_readiness_card_explains_previous_shutdown_and_timing_chain():
    text = _text()
    assert "ups_power" in text
    assert "unclean" in text
    assert "normal" in text
    for attribute in (
        "guest_shutdown_total_seconds",
        "outage_to_fsd_seconds",
        "fsd_to_all_guests_stopped_seconds",
        "fsd_to_shutdown_seconds",
        "all_guests_stopped_to_shutdown_seconds",
    ):
        assert attribute in text


def test_shutdown_readiness_card_uses_dedicated_budget_entity_not_policy_attribute():
    text = _text()
    assert "entity: sensor.dh_pve_ups_guest_shutdown_budget" in text
    assert "state_attr(entity, 'guest_shutdown_budget_seconds')" not in text
    assert "entity: sensor.dh_pve_ups_shutdown_readiness" in text
    assert "state_attr(entity, 'issues')" in text
    assert "is_state(entity, 'ok')" in text
    assert "is_state(entity, 'warning')" in text
