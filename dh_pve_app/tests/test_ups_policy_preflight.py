import os
from pathlib import Path

from app.config import UpsConfig
from app.ups_policy import PolicySafetyFacts
from app.ups_policy_preflight import read_policy_preflight
from app.ups_shutdown_policy import UpsShutdownPolicy


class Runner:
    def __init__(self):
        self.commands = []

    def __call__(self, command, **kwargs):
        self.commands.append(tuple(command))
        if command[:2] == ["systemctl", "is-active"]:
            service = command[2]
            state = "active\n" if service in {"nut-driver@ups.service", "nut-server.service"} else "inactive\n"
            code = 0 if state.strip() == "active" else 3
            return type("Result", (), {"returncode": code, "stdout": state, "stderr": ""})()
        raise AssertionError(f"unexpected command: {command}")


def _config():
    return UpsConfig(
        enabled=True,
        name="ups",
        host="127.0.0.1",
        port=3493,
        poll_interval_seconds=5.0,
        command_timeout_seconds=3.0,
    )


def _commissioning_policy():
    return UpsShutdownPolicy(
        state="Commissioning",
        role="primary",
        nut_monitor="inactive",
        shutdown_enabled=False,
        shutdown_command="/bin/true",
        min_supplies=1,
        pollfreq_seconds=5,
        pollfreqalert_seconds=5,
        deadtime_seconds=15,
        hostsync_seconds=120,
        finaldelay_seconds=5,
        upssched_present=False,
        upssched_rules=0,
        upssched_active=False,
        guest_shutdown_budget_seconds=None,
        power_restore_behavior="Not configured",
    )


def _facts():
    return PolicySafetyFacts(
        guest_shutdown_budget_seconds=280,
        hostsync_seconds=120,
        finaldelay_seconds=5,
        ups_poweroff_delay_seconds=60,
    )


def _seed(tmp_path):
    ups_conf = tmp_path / "ups.conf"
    ups_conf.write_text(
        '[ups]\n    driver = "usbhid-ups"\n    offdelay = 60\n    ondelay = 120\n',
        encoding="utf-8",
    )
    helper = tmp_path / "dh-pve-ups-policy-cmd"
    helper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    helper.chmod(0o755)
    return ups_conf, helper


def _preflight_kwargs(helper):
    return {
        "helper_path": helper,
        "helper_expected_uid": os.getuid(),
        "helper_expected_gid": os.getgid(),
    }


def test_preflight_ready_is_read_only_and_requires_safe_commissioning_state(tmp_path):
    ups_conf, helper = _seed(tmp_path)
    runner = Runner()

    report = read_policy_preflight(
        _config(),
        runner=runner,
        ups_reader=lambda config: object(),
        shutdown_policy_reader=_commissioning_policy,
        facts_reader=lambda config: _facts(),
        ups_conf_path=ups_conf,
        killpower_path=tmp_path / "killpower",
        **_preflight_kwargs(helper),
    )

    assert report.state == "Ready"
    assert report.ready is True
    assert report.as_dict()["guest_shutdown_budget_seconds"] == 280
    assert all(check.ok for check in report.checks)
    assert runner.commands == [
        ("systemctl", "is-active", "nut-driver@ups.service"),
        ("systemctl", "is-active", "nut-server.service"),
    ]


def test_preflight_blocks_if_monitor_is_already_live_or_shutdown_is_enabled(tmp_path):
    ups_conf, helper = _seed(tmp_path)
    policy = _commissioning_policy()
    policy = UpsShutdownPolicy(**{
        **policy.__dict__,
        "state": "Enabled",
        "nut_monitor": "active",
        "shutdown_enabled": True,
        "shutdown_command": "/sbin/shutdown -h now",
    })

    report = read_policy_preflight(
        _config(),
        runner=Runner(),
        ups_reader=lambda config: object(),
        shutdown_policy_reader=lambda: policy,
        facts_reader=lambda config: _facts(),
        ups_conf_path=ups_conf,
        killpower_path=tmp_path / "killpower",
        **_preflight_kwargs(helper),
    )

    assert report.state == "Blocked"
    assert report.ready is False
    failed = {check.key for check in report.checks if not check.ok}
    assert "monitor_inactive" in failed
    assert "shutdown_noop" in failed


def test_preflight_blocks_for_hardware_low_battery_override(tmp_path):
    ups_conf, helper = _seed(tmp_path)
    ups_conf.write_text(
        '[ups]\n    driver = "usbhid-ups"\n    ignorelb\n    offdelay = 60\n',
        encoding="utf-8",
    )

    report = read_policy_preflight(
        _config(),
        runner=Runner(),
        ups_reader=lambda config: object(),
        shutdown_policy_reader=_commissioning_policy,
        facts_reader=lambda config: _facts(),
        ups_conf_path=ups_conf,
        killpower_path=tmp_path / "killpower",
        **_preflight_kwargs(helper),
    )

    failed = {check.key: check.detail for check in report.checks if not check.ok}
    assert "hardware_lb_native" in failed
    assert "ignorelb" in failed["hardware_lb_native"].lower()


def test_preflight_blocks_when_killpower_flag_exists(tmp_path):
    ups_conf, helper = _seed(tmp_path)
    killpower = tmp_path / "killpower"
    killpower.write_text("1\n", encoding="utf-8")

    report = read_policy_preflight(
        _config(),
        runner=Runner(),
        ups_reader=lambda config: object(),
        shutdown_policy_reader=_commissioning_policy,
        facts_reader=lambda config: _facts(),
        ups_conf_path=ups_conf,
        killpower_path=killpower,
        **_preflight_kwargs(helper),
    )

    failed = {check.key for check in report.checks if not check.ok}
    assert "killpower_absent" in failed
