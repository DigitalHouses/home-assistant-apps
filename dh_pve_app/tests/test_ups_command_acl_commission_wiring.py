import app.ups_commission as commission_module
from app.config import UpsConfig
from app.ups_nut import parse_upsc_output
from app.ups_policy import PolicyApplyResult, PolicySafetyFacts
from app.ups_shutdown_policy import UpsShutdownPolicy


def _ups():
    return UpsConfig(
        enabled=True,
        name="ups",
        host="127.0.0.1",
        port=3493,
        poll_interval_seconds=5.0,
        command_timeout_seconds=3.0,
    )


def _facts():
    return PolicySafetyFacts(
        guest_shutdown_budget_seconds=280,
        hostsync_seconds=120,
        finaldelay_seconds=5,
        ups_poweroff_delay_seconds=60,
    )


def _policy():
    return UpsShutdownPolicy(
        state="Enabled",
        role="primary",
        nut_monitor="active",
        shutdown_enabled=True,
        shutdown_command="/sbin/shutdown -h now",
        min_supplies=1,
        pollfreq_seconds=5,
        pollfreqalert_seconds=5,
        deadtime_seconds=15,
        hostsync_seconds=120,
        finaldelay_seconds=5,
        upssched_present=True,
        upssched_rules=2,
        upssched_active=True,
        guest_shutdown_budget_seconds=280,
        power_restore_behavior="native",
        on_battery_delay_minutes=30,
        power_restore_delay_seconds=120,
    )


def test_commissioning_wires_safe_credential_verifier_into_applier(monkeypatch, tmp_path):
    snapshot = parse_upsc_output(
        "ups.status: OL\nups.delay.start: 120\nups.test.result: No test initiated\n"
    )
    captured = {}
    auth_calls = []

    class FakeApplier:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def apply(self, draft, facts):
            return PolicyApplyResult(True, "ok")

    monkeypatch.setattr(
        commission_module,
        "read_policy_safety_facts",
        lambda config: _facts(),
    )
    monkeypatch.setattr(
        commission_module,
        "verify_nut_credentials",
        lambda **kwargs: auth_calls.append(kwargs),
        raising=False,
    )

    result = commission_module.commission_ups_policy(
        _ups(),
        on_battery_delay_minutes=30,
        power_restore_delay_seconds=120,
        geteuid=lambda: 0,
        ups_reader=lambda config: snapshot,
        shutdown_policy_reader=lambda: _policy(),
        killpower_path=tmp_path / "killpower",
        applier_factory=FakeApplier,
    )

    assert result == PolicyApplyResult(True, "ok")
    verifier = captured["credential_verifier"]
    verifier("dh_primary_user", "super-secret")
    assert auth_calls == [
        {
            "host": "127.0.0.1",
            "port": 3493,
            "ups_name": "ups",
            "username": "dh_primary_user",
            "password": "super-secret",
            "timeout_seconds": 3.0,
        }
    ]
