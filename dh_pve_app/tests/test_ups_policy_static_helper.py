import os
from pathlib import Path

from app.ups_policy import PolicySafetyFacts, UpsPolicyDraft
from app.ups_policy_apply import ManagedNutPaths, UpsPolicyApplier


UPSMON = '''MONITOR ups@127.0.0.1 1 dh_primary_user secret primary
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


class Runner:
    def __init__(self):
        self.commands = []

    def __call__(self, command, **kwargs):
        self.commands.append(tuple(command))
        if command[:3] == ["systemctl", "is-active", "nut-monitor.service"]:
            return type("Result", (), {"returncode": 3, "stdout": "inactive\n", "stderr": ""})()
        if command[:3] == ["systemctl", "is-enabled", "nut-monitor.service"]:
            return type("Result", (), {"returncode": 1, "stdout": "disabled\n", "stderr": ""})()
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()


def test_policy_helper_is_static_app_code_not_writable_state():
    paths = ManagedNutPaths()

    assert paths.command_script == Path(
        "/opt/digitalhouses/dh_pve_app/bin/dh-pve-ups-policy-cmd"
    )
    assert not str(paths.command_script).startswith("/var/lib/")


def test_static_helper_source_is_restricted_to_owned_fsd_timer_token():
    helper = Path("dh_pve_app/bin/dh-pve-ups-policy-cmd").read_text(encoding="utf-8")

    assert '"dh-pve-ups-shutdown")' in helper
    assert "exec /sbin/upsmon -c fsd" in helper
    assert "*) exit 64" in helper
    assert "$@" not in helper
    assert "eval" not in helper


def test_installer_makes_static_helper_executable_but_service_cannot_write_opt():
    installer = Path("dh_pve_app/install.sh").read_text(encoding="utf-8")
    unit = Path("dh_pve_app/systemd/dh_pve_app.service").read_text(encoding="utf-8")

    assert 'chmod 0755 "${APP_DIR}/bin/dh-pve-ups-policy-cmd"' in installer
    assert "ProtectSystem=full" in unit
    assert "ReadWritePaths=/etc/nut" in unit
    assert "ReadWritePaths=/opt" not in unit


def test_applier_never_rewrites_static_helper(tmp_path):
    helper = tmp_path / "bin" / "dh-pve-ups-policy-cmd"
    helper.parent.mkdir()
    helper.write_text("STATIC-HELPER\n", encoding="utf-8")
    helper.chmod(0o755)

    paths = ManagedNutPaths(
        upsmon=tmp_path / "upsmon.conf",
        upssched=tmp_path / "upssched.conf",
        ups_conf=tmp_path / "ups.conf",
        command_script=helper,
        metadata=tmp_path / "policy.json",
    )
    paths.upsmon.write_text(UPSMON, encoding="utf-8")
    paths.ups_conf.write_text(UPS_CONF, encoding="utf-8")

    applier = UpsPolicyApplier(
        paths=paths,
        ups_name="ups",
        runner=Runner(),
        effective_restart_delay_reader=lambda: 180,
        helper_expected_uid=os.getuid(),
        helper_expected_gid=os.getgid(),
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

    assert result.success is True
    assert helper.read_text(encoding="utf-8") == "STATIC-HELPER\n"
