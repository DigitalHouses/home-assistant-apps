import os

from app.ups_policy import PolicySafetyFacts, UpsPolicyDraft
from app.ups_policy_apply import ManagedNutPaths, UpsPolicyApplier


UPSMON = '''MONITOR ups@127.0.0.1 1 dh_primary_user old-secret primary
MINSUPPLIES 1
HOSTSYNC 120
FINALDELAY 5
SHUTDOWNCMD "/bin/true"
'''

UPS_CONF = '''[ups]
    driver = "usbhid-ups"
    port = "auto"
    offdelay = 60
    ondelay = 120
'''

UPSD_USERS = '''[dh_primary_user]
    password = existing-secret
    upsmon primary
    instcmds = ALL
'''

APP_CONFIG = '''[ups]
enabled = true
name = ups
host = 127.0.0.1
port = 3493
poll_interval_seconds = 5
command_timeout_seconds = 3
command_username = legacy
command_password = legacy-secret
'''

HELPER = '''#!/bin/sh
set -eu
case "${1:-}" in
  "dh-pve-ups-shutdown") exec /sbin/upsmon -c fsd ;;
  *) exit 64 ;;
esac
'''


def _result(returncode=0, stdout="", stderr=""):
    return type(
        "Result",
        (),
        {"returncode": returncode, "stdout": stdout, "stderr": stderr},
    )()


class UnknownAppStateRunner:
    def __init__(self):
        self.events = []

    def __call__(self, command, **kwargs):
        self.events.append(" ".join(command))
        if command[:3] == ["systemctl", "is-active", "nut-monitor.service"]:
            return _result(3, "inactive\n")
        if command[:3] == ["systemctl", "is-enabled", "nut-monitor.service"]:
            return _result(1, "disabled\n")
        if command[:3] == ["systemctl", "is-active", "nut-server.service"]:
            return _result(0, "active\n")
        if command[:3] == ["systemctl", "is-enabled", "nut-server.service"]:
            return _result(0, "enabled\n")
        if command[:3] == ["systemctl", "is-active", "dh_pve_app.service"]:
            return _result(1, "")
        return _result()


def test_commissioning_fails_before_mutation_when_app_service_state_is_unknown(tmp_path):
    paths = ManagedNutPaths(
        upsmon=tmp_path / "nut" / "upsmon.conf",
        upssched=tmp_path / "nut" / "upssched.conf",
        ups_conf=tmp_path / "nut" / "ups.conf",
        upsd_users=tmp_path / "nut" / "upsd.users",
        app_config=tmp_path / "app" / "dh_pve_app.conf",
        command_script=tmp_path / "bin" / "dh-pve-ups-policy-cmd",
        metadata=tmp_path / "state" / "policy.json",
    )
    paths.upsmon.parent.mkdir(parents=True)
    paths.app_config.parent.mkdir(parents=True)
    paths.command_script.parent.mkdir(parents=True)
    paths.metadata.parent.mkdir(parents=True)
    paths.upsmon.write_text(UPSMON, encoding="utf-8")
    paths.ups_conf.write_text(UPS_CONF, encoding="utf-8")
    paths.upsd_users.write_text(UPSD_USERS, encoding="utf-8")
    paths.app_config.write_text(APP_CONFIG, encoding="utf-8")
    paths.command_script.write_text(HELPER, encoding="utf-8")
    paths.command_script.chmod(0o755)

    before = {
        path: path.read_bytes()
        for path in (
            paths.upsmon,
            paths.ups_conf,
            paths.upsd_users,
            paths.app_config,
        )
    }
    runner = UnknownAppStateRunner()
    applier = UpsPolicyApplier(
        paths=paths,
        ups_name="ups",
        runner=runner,
        effective_restart_delay_reader=lambda: 180,
        helper_expected_uid=os.getuid(),
        helper_expected_gid=os.getgid(),
        credential_verifier=lambda username, password: None,
    )

    result = applier.apply(
        UpsPolicyDraft(
            on_battery_delay_minutes=30,
            power_restore_delay_seconds=180,
        ),
        PolicySafetyFacts(
            guest_shutdown_budget_seconds=280,
            hostsync_seconds=120,
            finaldelay_seconds=5,
            ups_poweroff_delay_seconds=60,
        ),
    )

    assert result.success is False
    assert "dh_pve_app.service" in result.message
    for path, content in before.items():
        assert path.read_bytes() == content
    assert not paths.upssched.exists()
    assert not paths.metadata.exists()
    assert not any(event.startswith("systemctl restart") for event in runner.events)
