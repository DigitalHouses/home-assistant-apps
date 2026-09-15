import os
from pathlib import Path

from app.config import UpsConfig
from app.ups_policy import PolicySafetyFacts
from app.ups_policy_preflight import read_policy_preflight
from app.ups_shutdown_policy import UpsShutdownPolicy


SECRET = "managed-secret"


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
        command_username="dh_primary_user",
        command_password=SECRET,
    )


def _enabled_policy():
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
    (tmp_path / "upsd.users").write_text(
        "[dh_primary_user]\n"
        f"password = {SECRET}\n"
        "upsmon primary\n"
        "instcmds = ALL\n",
        encoding="utf-8",
    )
    (tmp_path / "upsmon.conf").write_text(
        f"MONITOR ups@127.0.0.1 1 dh_primary_user {SECRET} primary\n"
        'SHUTDOWNCMD "/sbin/shutdown -h now"\n',
        encoding="utf-8",
    )
    (tmp_path / "dh_pve_app.conf").write_text(
        "[general]\nnode_name = PVE\n\n"
        "[mqtt]\nhost = mqtt\n\n"
        "[ups]\n"
        "enabled = true\n"
        "name = ups\n"
        "command_username = dh_primary_user\n"
        f"command_password = {SECRET}\n",
        encoding="utf-8",
    )
    return ups_conf, helper


def _preflight_kwargs(helper):
    root = helper.parent
    return {
        "helper_path": helper,
        "helper_expected_uid": os.getuid(),
        "helper_expected_gid": os.getgid(),
        "upsd_users_path": root / "upsd.users",
        "upsmon_path": root / "upsmon.conf",
        "app_config_path": root / "dh_pve_app.conf",
    }


def test_preflight_ready_requires_live_primary_native_shutdown_path(tmp_path):
    ups_conf, helper = _seed(tmp_path)
    runner = Runner()

    report = read_policy_preflight(
        _config(),
        runner=runner,
        ups_reader=lambda config: object(),
        shutdown_policy_reader=_enabled_policy,
        facts_reader=lambda config: _facts(),
        ups_conf_path=ups_conf,
        killpower_path=tmp_path / "killpower",
        **_preflight_kwargs(helper),
    )

    assert report.state == "Ready"
    assert report.ready is True
    assert report.as_dict()["guest_shutdown_budget_seconds"] == 280
    assert all(check.ok for check in report.checks)
    assert SECRET not in repr(report.as_dict())
    assert runner.commands == [
        ("systemctl", "is-active", "nut-driver@ups.service"),
        ("systemctl", "is-active", "nut-server.service"),
    ]


def test_preflight_blocks_if_primary_monitor_or_native_shutdown_path_is_disabled(tmp_path):
    ups_conf, helper = _seed(tmp_path)
    policy = _enabled_policy()
    policy = UpsShutdownPolicy(**{
        **policy.__dict__,
        "state": "Commissioning",
        "nut_monitor": "inactive",
        "shutdown_enabled": False,
        "shutdown_command": "/bin/true",
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
    assert "monitor_active" in failed
    assert "shutdown_enabled" in failed


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
        shutdown_policy_reader=_enabled_policy,
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
        shutdown_policy_reader=_enabled_policy,
        facts_reader=lambda config: _facts(),
        ups_conf_path=ups_conf,
        killpower_path=killpower,
        **_preflight_kwargs(helper),
    )

    failed = {check.key for check in report.checks if not check.ok}
    assert "killpower_absent" in failed
