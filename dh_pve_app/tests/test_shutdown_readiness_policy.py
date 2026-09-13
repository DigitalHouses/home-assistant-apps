from types import SimpleNamespace

from app.shutdown_history import evaluate_shutdown_readiness
from app.shutdown_integration import shutdown_policy_issues


def _policy(**overrides):
    values = {
        "state": "Enabled",
        "role": "primary",
        "nut_monitor": "active",
        "shutdown_enabled": True,
        "upssched_present": True,
        "upssched_active": True,
        "on_battery_delay_minutes": 30,
        "power_restore_delay_seconds": 120,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_enabled_production_policy_has_no_readiness_issues():
    assert shutdown_policy_issues(_policy(), nut_available=True) == []


def test_broken_production_policy_is_reported_as_warning():
    issues = shutdown_policy_issues(
        _policy(
            state="Unknown",
            role="secondary",
            nut_monitor="inactive",
            shutdown_enabled=False,
            upssched_active=False,
            on_battery_delay_minutes=None,
        ),
        nut_available=False,
    )

    assert "nut_unavailable" in issues
    assert "shutdown_policy_not_enabled" in issues
    assert "nut_role_not_primary" in issues
    assert "nut_monitor_not_active" in issues
    assert "shutdown_disabled" in issues
    assert "upssched_inactive" in issues
    assert "on_battery_delay_unreadable" in issues

    readiness = evaluate_shutdown_readiness(
        ups_present=True,
        guest_shutdown_budget_seconds=420,
        previous_shutdown=None,
        additional_issues=issues,
    )
    assert readiness["status"] == "warning"
    assert "nut_monitor_not_active" in readiness["issues"]


def test_missing_policy_is_not_ready():
    issues = shutdown_policy_issues(None, nut_available=True)
    assert issues == ["shutdown_policy_unavailable"]
