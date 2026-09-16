from pathlib import Path

from app.ups_legacy_timer import (
    legacy_timer_present,
    retire_legacy_timer_text,
)


UPSCHED_MANAGED = """\
# DigitalHouses managed UPS shutdown schedule
CMDSCRIPT /opt/digitalhouses/dh_pve_app/bin/dh-pve-ups-policy-cmd
PIPEFN /run/nut/upssched.pipe
LOCKFN /run/nut/upssched.lock
AT ONBATT * START-TIMER dh-pve-ups-shutdown 1800
AT ONLINE * CANCEL-TIMER dh-pve-ups-shutdown
"""

UPSMON_MANAGED = """\
MONITOR ups@127.0.0.1 1 user pass primary
SHUTDOWNCMD \"/sbin/shutdown -h now\"
NOTIFYCMD /usr/sbin/upssched
NOTIFYFLAG ONBATT SYSLOG+EXEC
NOTIFYFLAG ONLINE SYSLOG+EXEC
"""


def test_detects_known_dh_v1_timer():
    assert legacy_timer_present(UPSCHED_MANAGED) is True


def test_retirement_removes_only_known_timer_and_detaches_exec_when_no_other_rules():
    upsmon, upssched = retire_legacy_timer_text(UPSMON_MANAGED, UPSCHED_MANAGED)

    assert "dh-pve-ups-shutdown" not in upssched
    assert "NOTIFYCMD /usr/sbin/upssched" not in upsmon
    assert "NOTIFYFLAG ONBATT SYSLOG" in upsmon
    assert "NOTIFYFLAG ONLINE SYSLOG" in upsmon
    assert "+EXEC" not in upsmon


def test_retirement_preserves_unrelated_upssched_rules_and_exec_dispatch():
    upssched_with_admin_rule = UPSCHED_MANAGED + "AT COMMBAD * EXECUTE admin-comms-alert\n"

    upsmon, upssched = retire_legacy_timer_text(
        UPSMON_MANAGED,
        upssched_with_admin_rule,
    )

    assert "dh-pve-ups-shutdown" not in upssched
    assert "AT COMMBAD * EXECUTE admin-comms-alert" in upssched
    assert "NOTIFYCMD /usr/sbin/upssched" in upsmon
    assert "NOTIFYFLAG ONBATT SYSLOG+EXEC" in upsmon
    assert "NOTIFYFLAG ONLINE SYSLOG+EXEC" in upsmon


def test_unrelated_upssched_config_is_unchanged():
    upsmon = "NOTIFYCMD /usr/sbin/upssched\nNOTIFYFLAG COMMBAD SYSLOG+EXEC\n"
    upssched = "AT COMMBAD * EXECUTE admin-comms-alert\n"

    new_upsmon, new_upssched = retire_legacy_timer_text(upsmon, upssched)

    assert new_upsmon == upsmon
    assert new_upssched == upssched
    assert legacy_timer_present(new_upssched) is False
