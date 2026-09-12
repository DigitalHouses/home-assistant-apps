import os
from pathlib import Path

from app.config import UpsConfig
from app.ups_policy import PolicySafetyFacts, UpsPolicyDraft
from app.ups_policy_apply import ManagedNutPaths, UpsPolicyApplier
from app.ups_policy_preflight import read_policy_preflight
from app.ups_shutdown_policy import UpsShutdownPolicy


UPSMON = '''MONITOR ups@127.0.0.1 1 dh_primary_user secret primary
MINSUPPLIES 1
HOSTSYNC 120
FINALDELAY 5
SHUTDOWNCMD "/bin/true"
'''
UPS_CONF = '''[ups]
    driver = "usbhid-ups"
    offdelay = 60
    ondelay = 120
'''


class Runner:
    def __call__(self, command, **kwargs):
        if command[:2] == ["systemctl", "is-active"]:
            service = command[2]
            if service in {"nut-driver@ups.service", "nut-server.service"}:
                return type("Result", (), {"returncode": 0, "stdout": "active\n", "stderr": ""})()
            return type("Result", (), {"returncode": 3, "stdout": "inactive\n", "stderr": ""})()
        if command[:3] == ["systemctl", "is-enabled", "nut-monitor.service"]:
            return type("Result", (), {"returncode": 1, "stdout": "disabled\n", "stderr": ""})()
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()


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


def _config():
    return UpsConfig(
        enabled=True,
        name="ups",
        host="127.0.0.1",
        port=3493,
        poll_interval_seconds=5.0,
        command_timeout_seconds=3.0,
    )


def _seed(tmp_path):
    helper = tmp_path / "helper"
    helper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    helper.chmod(0o755)
    ups_conf = tmp_path / "ups.conf"
    ups_conf.write_text(UPS_CONF, encoding="utf-8")
    return helper, ups_conf


def test_applier_rejects_helper_owned_by_untrusted_uid(tmp_path):
    helper, _ = _seed(tmp_path)
    paths = ManagedNutPaths(
        upsmon=tmp_path / "upsmon.conf",
        upssched=tmp_path / "upssched.conf",
        ups_conf=tmp_path / "ups.conf",
        command_script=helper,
        metadata=tmp_path / "policy.json",
    )
    paths.upsmon.write_text(UPSMON, encoding="utf-8")

    result = UpsPolicyApplier(
        paths=paths,
        ups_name="ups",
        runner=Runner(),
        effective_restart_delay_reader=lambda: 180,
        helper_expected_uid=os.getuid() + 1,
        helper_expected_gid=os.getgid(),
    ).apply(
        UpsPolicyDraft(
            on_battery_delay_minutes=30,
            power_restore_delay_seconds=180,
        ),
        _facts(),
    )

    assert result.success is False
    assert "владел" in result.message.lower() or "uid" in result.message.lower()


def test_preflight_blocks_helper_with_untrusted_owner(tmp_path):
    helper, ups_conf = _seed(tmp_path)

    report = read_policy_preflight(
        _config(),
        runner=Runner(),
        ups_reader=lambda config: object(),
        shutdown_policy_reader=_policy,
        facts_reader=lambda config: _facts(),
        ups_conf_path=ups_conf,
        helper_path=helper,
        helper_expected_uid=os.getuid() + 1,
        helper_expected_gid=os.getgid(),
        killpower_path=tmp_path / "killpower",
    )

    failed = {check.key: check.detail for check in report.checks if not check.ok}
    assert "helper_secure" in failed
    assert "uid" in failed["helper_secure"].lower() or "владел" in failed["helper_secure"].lower()
