from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CARD = ROOT / "examples" / "dh_app_pve_shutdown_readiness_card.yaml"


def _text() -> str:
    return CARD.read_text(encoding="utf-8")


def test_shutdown_readiness_card_uses_canonical_backend_entities():
    assert CARD.is_file()
    text = _text()

    for entity_id in (
        "sensor.dh_app_pve_previous_shutdown",
        "sensor.dh_app_pve_shutdown_history",
        "sensor.dh_app_pve_ups_shutdown_readiness",
        "sensor.dh_app_pve_ups_guest_shutdown_budget",
    ):
        assert entity_id in text


def test_shutdown_readiness_card_keeps_cause_and_cleanliness_separate():
    text = _text()

    assert "shutdown_reason" in text
    assert "shutdown_clean" in text
    assert "ups_power" in text
    assert "unclean" in text


def test_shutdown_readiness_card_uses_backend_budget_and_readiness_without_join_scan():
    text = _text()

    assert "sensor.dh_app_pve_ups_guest_shutdown_budget" in text
    assert "sensor.dh_app_pve_ups_shutdown_readiness" in text
    assert "states.sensor" not in text
    assert "states.binary_sensor" not in text
    assert "proxmox_metric" not in text


def test_shutdown_readiness_card_contains_no_legacy_public_entity_ids():
    text = _text()

    assert ".dh_pve_" not in text
    assert ".dh_pve_ups_" not in text
