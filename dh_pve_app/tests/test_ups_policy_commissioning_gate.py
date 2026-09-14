import app.ups_commission as commission_module
from app.config import UpsConfig
from app.ups_nut import parse_upsc_output
from app.ups_policy import PolicyApplyResult, PolicySafetyFacts, UpsPolicyDraft
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
        host_shutdown_reserve_seconds=60,
        ups_poweroff_delay_seconds=60,
        safety_margin_seconds=60,
    )


def _policy(role="primary"):
    return UpsShutdownPolicy(
        state="Enabled",
        role=role,
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


def test_commissioning_requires_root():
    result = commission_module.commission_ups_policy(
        _ups(),
        on_battery_delay_minutes=30,
        power_restore_delay_seconds=120,
        geteuid=lambda: 1000,
        ups_reader=lambda config: (_ for _ in ()).throw(
            AssertionError("must not read UPS without root")
        ),
    )

    assert result.success is False
    assert "root" in result.message


def test_commissioning_refuses_on_battery():
    snapshot = parse_upsc_output(
        "ups.status: OB DISCHRG\nups.delay.start: 120\nups.test.result: No test initiated\n"
    )
    result = commission_module.commission_ups_policy(
        _ups(),
        on_battery_delay_minutes=30,
        power_restore_delay_seconds=120,
        geteuid=lambda: 0,
        ups_reader=lambda config: snapshot,
    )

    assert result.success is False
    assert "OL" in result.message


def test_commissioning_refuses_during_battery_test():
    snapshot = parse_upsc_output(
        "ups.status: OL\nups.delay.start: 120\nups.test.result: In progress\n"
    )
    result = commission_module.commission_ups_policy(
        _ups(),
        on_battery_delay_minutes=30,
        power_restore_delay_seconds=120,
        geteuid=lambda: 0,
        ups_reader=lambda config: snapshot,
    )

    assert result.success is False
    assert "тест" in result.message.casefold()


def test_commissioning_refuses_non_primary_role(tmp_path):
    snapshot = parse_upsc_output(
        "ups.status: OL\nups.delay.start: 120\nups.test.result: No test initiated\n"
    )
    result = commission_module.commission_ups_policy(
        _ups(),
        on_battery_delay_minutes=30,
        power_restore_delay_seconds=120,
        geteuid=lambda: 0,
        ups_reader=lambda config: snapshot,
        shutdown_policy_reader=lambda: _policy("secondary"),
        killpower_path=tmp_path / "killpower",
    )

    assert result.success is False
    assert "PRIMARY" in result.message
    assert "secondary" in result.message


def test_commissioning_refuses_existing_killpower(tmp_path):
    snapshot = parse_upsc_output(
        "ups.status: OL\nups.delay.start: 120\nups.test.result: No test initiated\n"
    )
    flag = tmp_path / "killpower"
    flag.write_text("1", encoding="utf-8")

    result = commission_module.commission_ups_policy(
        _ups(),
        on_battery_delay_minutes=30,
        power_restore_delay_seconds=120,
        geteuid=lambda: 0,
        ups_reader=lambda config: snapshot,
        killpower_path=flag,
    )

    assert result.success is False
    assert "POWERDOWNFLAG" in result.message


def test_commissioning_builds_writer_only_for_explicit_safe_call(monkeypatch, tmp_path):
    snapshot = parse_upsc_output(
        "ups.status: OL\nups.delay.start: 120\nups.test.result: No test initiated\n"
    )
    captured = {}

    class FakeApplier:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def apply(self, draft, facts):
            captured["draft"] = draft
            captured["facts"] = facts
            return PolicyApplyResult(True, "ok")

    monkeypatch.setattr(
        commission_module,
        "read_policy_safety_facts",
        lambda config: _facts(),
    )

    result = commission_module.commission_ups_policy(
        _ups(),
        on_battery_delay_minutes=30,
        power_restore_delay_seconds=120,
        geteuid=lambda: 0,
        ups_reader=lambda config: snapshot,
        shutdown_policy_reader=lambda: _policy("primary"),
        killpower_path=tmp_path / "killpower",
        applier_factory=FakeApplier,
    )

    assert result == PolicyApplyResult(True, "ok")
    assert captured["ups_name"] == "ups"
    assert captured["effective_restart_delay_reader"]() == 120
    assert captured["draft"] == UpsPolicyDraft(30, 120)
    assert captured["facts"] == _facts()
