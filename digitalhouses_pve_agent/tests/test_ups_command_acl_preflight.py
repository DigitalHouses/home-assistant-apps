import os

from app.config import UpsConfig
from app.ups_policy import PolicySafetyFacts
from app.ups_policy_preflight import read_policy_preflight
from app.ups_shutdown_policy import UpsShutdownPolicy


SECRET = "managed-super-secret"


class Runner:
    def __call__(self, command, **kwargs):
        if command[:2] == ["systemctl", "is-active"]:
            service = command[2]
            state = "active\n" if service in {"nut-driver@ups.service", "nut-server.service"} else "inactive\n"
            return type(
                "Result",
                (),
                {"returncode": 0 if state.strip() == "active" else 3, "stdout": state, "stderr": ""},
            )()
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


def _policy():
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


def _seed(tmp_path, *, user_block=None, monitor_user="dh_primary_user", monitor_password=SECRET, app_user="dh_primary_user", app_password=SECRET):
    ups_conf = tmp_path / "ups.conf"
    ups_conf.write_text(
        '[ups]\n    driver = "usbhid-ups"\n    offdelay = 60\n    ondelay = 120\n',
        encoding="utf-8",
    )
    helper = tmp_path / "dh-pve-ups-policy-cmd"
    helper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    helper.chmod(0o755)

    upsd_users = tmp_path / "upsd.users"
    if user_block is None:
        user_block = (
            "[dh_primary_user]\n"
            f"    password = {SECRET}\n"
            "    upsmon primary\n"
            "    instcmds = ALL\n"
        )
    upsd_users.write_text(user_block, encoding="utf-8")

    upsmon = tmp_path / "upsmon.conf"
    upsmon.write_text(
        f"MONITOR ups@127.0.0.1 1 {monitor_user} {monitor_password} primary\n"
        'SHUTDOWNCMD "/bin/true"\n',
        encoding="utf-8",
    )

    app_config = tmp_path / "dh_pve_app.conf"
    app_config.write_text(
        "[general]\nnode_name = PVE\n\n"
        "[mqtt]\nhost = 192.168.11.33\n\n"
        "[ups]\n"
        "enabled = true\n"
        "name = ups\n"
        f"command_username = {app_user}\n"
        f"command_password = {app_password}\n",
        encoding="utf-8",
    )
    return ups_conf, helper, upsd_users, upsmon, app_config


def _run(tmp_path, **seed_kwargs):
    ups_conf, helper, users, upsmon, app_config = _seed(tmp_path, **seed_kwargs)
    return read_policy_preflight(
        _config(),
        runner=Runner(),
        ups_reader=lambda config: object(),
        shutdown_policy_reader=_policy,
        facts_reader=lambda config: _facts(),
        ups_conf_path=ups_conf,
        upsd_users_path=users,
        upsmon_path=upsmon,
        app_config_path=app_config,
        helper_path=helper,
        helper_expected_uid=os.getuid(),
        helper_expected_gid=os.getgid(),
        killpower_path=tmp_path / "killpower",
    )


def test_preflight_accepts_one_consistent_primary_control_identity_without_leaking_secret(tmp_path):
    report = _run(tmp_path)

    checks = {check.key: check for check in report.checks}
    assert checks["nut_primary_user"].ok is True
    assert checks["nut_primary_role"].ok is True
    assert checks["nut_instcmds_all"].ok is True
    assert checks["monitor_identity"].ok is True
    assert checks["app_command_identity"].ok is True
    assert checks["credentials_consistent"].ok is True
    assert SECRET not in repr(report.as_dict())


def test_preflight_blocks_when_primary_user_is_missing(tmp_path):
    report = _run(
        tmp_path,
        user_block="[secondary]\npassword = other\nupsmon secondary\n",
    )

    failed = {check.key for check in report.checks if not check.ok}
    assert "nut_primary_user" in failed
    assert report.ready is False


def test_preflight_blocks_when_primary_user_lacks_all_instcmds(tmp_path):
    report = _run(
        tmp_path,
        user_block=(
            "[dh_primary_user]\n"
            f"password = {SECRET}\n"
            "upsmon primary\n"
            "instcmds = test.battery.start.quick\n"
        ),
    )

    failed = {check.key for check in report.checks if not check.ok}
    assert "nut_instcmds_all" in failed


def test_preflight_blocks_when_monitor_or_app_uses_another_identity(tmp_path):
    report = _run(
        tmp_path,
        monitor_user="legacy_user",
        app_user="legacy_user",
    )

    failed = {check.key for check in report.checks if not check.ok}
    assert "monitor_identity" in failed
    assert "app_command_identity" in failed


def test_preflight_blocks_when_managed_passwords_do_not_match(tmp_path):
    report = _run(tmp_path, app_password="different-secret")

    failed = {check.key for check in report.checks if not check.ok}
    assert "credentials_consistent" in failed
    details = " ".join(check.detail for check in report.checks)
    assert SECRET not in details
    assert "different-secret" not in details
