from app.ups_semantics import (
    CANONICAL_STATUS_ORDER,
    PRIMARY_STATUS_PRECEDENCE,
    normalize_ups_status,
    primary_ups_status,
    resolve_charger_status,
)


def test_canonical_status_order_is_stable_and_excludes_charger_tokens():
    assert CANONICAL_STATUS_ORDER == (
        "online",
        "on_battery",
        "low_battery",
        "high_battery",
        "replace_battery",
        "bypass",
        "calibration",
        "output_off",
        "overload",
        "trim",
        "boost",
        "forced_shutdown",
        "alarm",
    )
    assert "charging" not in CANONICAL_STATUS_ORDER
    assert "discharging" not in CANONICAL_STATUS_ORDER


def test_primary_status_precedence_matches_canonical_design():
    assert PRIMARY_STATUS_PRECEDENCE == (
        "forced_shutdown",
        "alarm",
        "overload",
        "replace_battery",
        "low_battery",
        "bypass",
        "calibration",
        "output_off",
        "on_battery",
        "boost",
        "trim",
        "high_battery",
        "online",
    )


def test_status_normalization_is_ordered_machine_only_and_future_tolerant():
    assert normalize_ups_status(("OL", "BOOST", "CHRG")) == ("online", "boost")
    assert normalize_ups_status(("OB", "DISCHRG", "LB")) == (
        "on_battery",
        "low_battery",
    )
    assert normalize_ups_status(("OL", "FUTURE_TOKEN")) == ("online",)
    assert normalize_ups_status(("LB", "OB", "LB")) == (
        "on_battery",
        "low_battery",
    )


def test_primary_status_uses_precedence_not_input_order():
    assert primary_ups_status(("online", "boost")) == "boost"
    assert primary_ups_status(("online", "low_battery", "on_battery")) == "low_battery"
    assert primary_ups_status(()) == "unknown"


def test_direct_charger_status_has_priority_when_recognized():
    assert resolve_charger_status(
        direct_status="floating",
        status_tokens=("OL", "CHRG"),
        line_power=True,
    ) == "floating"
    assert resolve_charger_status(
        direct_status=" RESTING ",
        status_tokens=("OL", "CHRG"),
        line_power=True,
    ) == "resting"


def test_legacy_charger_fallback_uses_raw_status_evidence():
    assert resolve_charger_status(
        direct_status=None,
        status_tokens=("OL", "CHRG"),
        line_power=True,
    ) == "charging"
    assert resolve_charger_status(
        direct_status=None,
        status_tokens=("OB", "DISCHRG"),
        line_power=False,
    ) == "discharging"
    assert resolve_charger_status(
        direct_status=None,
        status_tokens=("OL",),
        line_power=True,
    ) == "idle"
    assert resolve_charger_status(
        direct_status=None,
        status_tokens=("OB",),
        line_power=False,
    ) == "unknown"


def test_unknown_direct_charger_value_is_not_guessed_from_legacy_tokens():
    assert resolve_charger_status(
        direct_status="vendor-weird",
        status_tokens=("OL", "CHRG"),
        line_power=True,
    ) == "unknown"
