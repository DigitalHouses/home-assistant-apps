from pathlib import Path

import pytest

from app.ups_policy import PolicySafetyFacts, UpsPolicyDraft
from app.ups_policy_apply import (
    ManagedNutPaths,
    PolicyApplyError,
    UpsPolicyApplier,
    render_managed_policy,
)


UPSMON_COMMISSIONING = '''# existing commissioning config
MONITOR ups@127.0.0.1 1 dh_primary_user secret primary
MINSUPPLIES 1
POLLFREQ 5
POLLFREQALERT 5
DEADTIME 15
HOSTSYNC 120
FINALDELAY 5
SHUTDOWNCMD "/bin/true"
'''

UPS_CONF = '''[ups]
    driver = "usbhid-ups"
    port = "auto"
    vendorid = "0764"
    productid = "0601"
    serial = "PTJGW2000085"
    offdelay = 60
    ondelay = 120
'''

HELPER = '''#!/bin/sh
set -eu
case "${1:-}" in
  "dh-pve-ups-shutdown") exec /sbin/upsmon -c fsd ;;
  *) exit 64 ;;
esac
'''


def _draft():
    return UpsPolicyDraft(
        on_battery_delay_minutes=30,
        power_restore_delay_seconds=180,
    )


def _facts():
    return PolicySafetyFacts(
        guest_shutdown_budget_seconds=280,
        hostsync_seconds=120,
        finaldelay_seconds=5,
        ups_poweroff_delay_seconds=60,
    )


def test_rendered_policy_uses_cancellable_onbatt_timer_and_native_lb():
    target = render_managed_policy(
        _draft(),
        UPSMON_COMMISSIONING,
        UPS_CONF,
        command_script_path=Path("/opt/digitalhouses/dh_pve_app/bin/dh-pve-ups-policy-cmd"),
    )

    assert 'SHUTDOWNCMD "/sbin/shutdown -h now"' in target.upsmon_text
    assert "POWERDOWNFLAG /etc/killpower" in target.upsmon_text
    assert "NOTIFYCMD /usr/sbin/upssched" in target.upsmon_text
    assert "NOTIFYFLAG ONBATT SYSLOG+EXEC" in target.upsmon_text
    assert "NOTIFYFLAG ONLINE SYSLOG+EXEC" in target.upsmon_text

    assert (
        "CMDSCRIPT /opt/digitalhouses/dh_pve_app/bin/dh-pve-ups-policy-cmd"
        in target.upssched_text
    )
    assert "PIPEFN /run/nut/upssched.pipe" in target.upssched_text
    assert "LOCKFN /run/nut/upssched.lock" in target.upssched_text
    assert "AT ONBATT * START-TIMER dh-pve-ups-shutdown 1800" in target.upssched_text
    assert "AT ONLINE * CANCEL-TIMER dh-pve-ups-shutdown" in target.upssched_text

    combined = "\n".join(
        (target.upsmon_text, target.upssched_text, target.ups_conf_text)
    ).lower()
    assert "ignorelb" not in combined
    assert "override.battery.runtime.low" not in combined
    assert "battery.runtime.low" not in combined
    assert "battery.charge.low" not in combined


def test_rendered_driver_policy_changes_restore_delay_but_preserves_safe_offdelay():
    target = render_managed_policy(
        _draft(),
        UPSMON_COMMISSIONING,
        UPS_CONF,
        command_script_path=Path("/opt/digitalhouses/dh_pve_app/bin/dh-pve-ups-policy-cmd"),
    )

    assert "offdelay = 60" in target.ups_conf_text
    assert "ondelay = 180" in target.ups_conf_text
    assert "serial = \"PTJGW2000085\"" in target.ups_conf_text


def test_rendered_driver_policy_raises_too_small_offdelay_to_60():
    target = render_managed_policy(
        _draft(),
        UPSMON_COMMISSIONING,
        UPS_CONF.replace("offdelay = 60", "offdelay = 30"),
        command_script_path=Path("/opt/digitalhouses/dh_pve_app/bin/dh-pve-ups-policy-cmd"),
    )

    assert "offdelay = 60" in target.ups_conf_text


class FakeRunner:
    def __init__(self, *, fail_contains: str | None = None):
        self.commands = []
        self.fail_contains = fail_contains

    def __call__(self, command, **kwargs):
        self.commands.append(tuple(command))
        text = " ".join(command)
        if self.fail_contains and self.fail_contains in text:
            return type("Result", (), {"returncode": 1, "stdout": "", "stderr": "boom"})()
        if command[:3] == ["systemctl", "is-active", "nut-monitor.service"]:
            return type("Result", (), {"returncode": 3, "stdout": "inactive\n", "stderr": ""})()
        if command[:3] == ["systemctl", "is-enabled", "nut-monitor.service"]:
            return type("Result", (), {"returncode": 1, "stdout": "disabled\n", "stderr": ""})()
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()


def _paths(tmp_path):
    return ManagedNutPaths(
        upsmon=tmp_path / "upsmon.conf",
        upssched=tmp_path / "upssched.conf",
        ups_conf=tmp_path / "ups.conf",
        command_script=tmp_path / "bin" / "dh-pve-ups-policy-cmd",
        metadata=tmp_path / "policy.json",
    )


def _seed(paths):
    paths.upsmon.write_text(UPSMON_COMMISSIONING, encoding="utf-8")
    paths.ups_conf.write_text(UPS_CONF, encoding="utf-8")
    paths.command_script.parent.mkdir(parents=True, exist_ok=True)
    paths.command_script.write_text(HELPER, encoding="utf-8")
    paths.command_script.chmod(0o755)


def test_apply_writes_only_mutable_policy_files_and_verifies_before_success(tmp_path):
    paths = _paths(tmp_path)
    _seed(paths)
    helper_before = paths.command_script.read_text(encoding="utf-8")
    runner = FakeRunner()

    applier = UpsPolicyApplier(
        paths=paths,
        ups_name="ups",
        runner=runner,
        effective_restart_delay_reader=lambda: 180,
    )
    result = applier.apply(_draft(), _facts())

    assert result.success is True
    assert "применена" in result.message.lower()
    assert paths.upssched.exists()
    assert paths.command_script.read_text(encoding="utf-8") == helper_before
    assert paths.metadata.exists()
    assert "ondelay = 180" in paths.ups_conf.read_text(encoding="utf-8")
    assert "battery.runtime.low" not in paths.ups_conf.read_text(encoding="utf-8")


def test_apply_fails_closed_when_static_helper_is_missing(tmp_path):
    paths = _paths(tmp_path)
    paths.upsmon.write_text(UPSMON_COMMISSIONING, encoding="utf-8")
    paths.ups_conf.write_text(UPS_CONF, encoding="utf-8")

    result = UpsPolicyApplier(
        paths=paths,
        ups_name="ups",
        runner=FakeRunner(),
        effective_restart_delay_reader=lambda: 180,
    ).apply(_draft(), _facts())

    assert result.success is False
    assert "helper" in result.message.lower() or "скрипт" in result.message.lower()


def test_apply_rolls_back_all_mutable_files_when_service_action_fails(tmp_path):
    paths = _paths(tmp_path)
    _seed(paths)
    before_upsmon = paths.upsmon.read_text(encoding="utf-8")
    before_ups_conf = paths.ups_conf.read_text(encoding="utf-8")
    helper_before = paths.command_script.read_text(encoding="utf-8")
    runner = FakeRunner(fail_contains="nut-driver@ups.service")

    applier = UpsPolicyApplier(
        paths=paths,
        ups_name="ups",
        runner=runner,
        effective_restart_delay_reader=lambda: 180,
    )
    result = applier.apply(_draft(), _facts())

    assert result.success is False
    assert paths.upsmon.read_text(encoding="utf-8") == before_upsmon
    assert paths.ups_conf.read_text(encoding="utf-8") == before_ups_conf
    assert not paths.upssched.exists()
    assert paths.command_script.read_text(encoding="utf-8") == helper_before
    assert not paths.metadata.exists()


def test_apply_rolls_back_when_effective_restart_delay_does_not_match(tmp_path):
    paths = _paths(tmp_path)
    _seed(paths)
    before = paths.upsmon.read_text(encoding="utf-8")

    applier = UpsPolicyApplier(
        paths=paths,
        ups_name="ups",
        runner=FakeRunner(),
        effective_restart_delay_reader=lambda: 120,
    )
    result = applier.apply(_draft(), _facts())

    assert result.success is False
    assert paths.upsmon.read_text(encoding="utf-8") == before


def test_render_rejects_missing_selected_ups_section():
    with pytest.raises(PolicyApplyError, match="UPS"):
        render_managed_policy(
            _draft(),
            UPSMON_COMMISSIONING,
            "[other]\ndriver = dummy-ups\n",
            command_script_path=Path(
                "/opt/digitalhouses/dh_pve_app/bin/dh-pve-ups-policy-cmd"
            ),
            ups_name="ups",
        )
