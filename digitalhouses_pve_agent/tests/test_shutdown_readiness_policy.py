from types import SimpleNamespace

from app.shutdown_history import evaluate_shutdown_readiness
from app.shutdown_integration import shutdown_policy_issues


def _policy(**overrides):
    values = {
        "state": "Enabled",
        "role": "primary",
        "nut_monitor": "active",
        "shutdown_enabled": True,
        # Trigger Policy v2 does not use the former upssched ONBATT timer.
        # These fields remain observable legacy diagnostics only.
        "upssched_present": False,
        "upssched_active": False,
        "on_battery_delay_minutes": None,
        "power_restore_delay_seconds": 120,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_enabled_production_policy_has_no_readiness_issues_without_legacy_timer():
    assert shutdown_policy_issues(_policy(), nut_available=True) == []


def test_legacy_upssched_timer_does_not_affect_v2_readiness():
    issues = shutdown_policy_issues(
        _policy(
            upssched_present=True,
            upssched_active=True,
            on_battery_delay_minutes=30,
        ),
        nut_available=True,
    )

    assert issues == []


def test_broken_production_policy_is_reported_as_warning():
    issues = shutdown_policy_issues(
        _policy(
            state="Unknown",
            role="secondary",
            nut_monitor="inactive",
            shutdown_enabled=False,
        ),
        nut_available=False,
    )

    assert "nut_unavailable" in issues
    assert "shutdown_policy_not_enabled" in issues
    assert "nut_role_not_primary" in issues
    assert "nut_monitor_not_active" in issues
    assert "shutdown_disabled" in issues
    assert "upssched_inactive" not in issues
    assert "on_battery_delay_unreadable" not in issues

    readiness = evaluate_shutdown_readiness(
        ups_present=True,
        guest_shutdown_budget_seconds=420,
        previous_shutdown=None,
        additional_issues=issues,
    )
    assert readiness["status"] == "warning"
    assert "nut_monitor_not_active" in readiness["issues"]


def test_missing_power_restore_delay_is_still_reported():
    issues = shutdown_policy_issues(
        _policy(power_restore_delay_seconds=None),
        nut_available=True,
    )

    assert issues == ["power_restore_delay_unreadable"]


def test_missing_policy_is_not_ready():
    issues = shutdown_policy_issues(None, nut_available=True)
    assert issues == ["shutdown_policy_unavailable"]


def test_readiness_uses_current_timeout_ratio_from_latest_guest_facts():
    previous_shutdown = {
        "shutdown_class": "ups_power",
        "shutdown_clean": True,
        "guests": {
            "vm": {
                "501": {
                    "result": "clean",
                    "forced": False,
                    "timeout_ratio": 0.933,
                }
            },
            "lxc": {
                "10001": {
                    "result": "clean",
                    "forced": False,
                    "timeout_ratio": 1.067,
                }
            },
        },
    }
    latest_guests = {
        "vm": {
            "501": {
                "result": "clean",
                "forced": False,
                "timeout_ratio": 0.933,
                "current_timeout_ratio": 0.56,
            }
        },
        "lxc": {
            "10001": {
                "result": "clean",
                "forced": False,
                "timeout_ratio": 1.067,
                "current_timeout_ratio": 0.64,
            }
        },
    }

    readiness = evaluate_shutdown_readiness(
        ups_present=True,
        guest_shutdown_budget_seconds=455,
        previous_shutdown=previous_shutdown,
        guest_shutdowns=latest_guests,
    )

    assert readiness["status"] == "ok"
    assert readiness["issues"] == []

