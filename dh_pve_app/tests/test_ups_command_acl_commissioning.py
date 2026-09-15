from pathlib import Path

import pytest

from app.ups_policy import UpsPolicyDraft
from app.ups_policy_apply import ManagedNutPaths, PolicyApplyError, render_managed_policy


UPSMON = '''MONITOR ups@127.0.0.1 1 legacy old-secret primary
MINSUPPLIES 1
SHUTDOWNCMD "/bin/true"
'''

UPS_CONF = '''[ups]
    driver = "usbhid-ups"
    port = "auto"
    offdelay = 60
    ondelay = 120
'''

UPSD_USERS = '''[secondary]
    password = secondary-secret
    upsmon secondary

[dh_primary_user]
    password = existing-secret
    upsmon primary
    instcmds = test.battery.start.quick
'''

APP_CONFIG = '''[general]
node_name = PVE

[mqtt]
host = 192.168.11.33

[ups]
enabled = true
name = ups
host = 127.0.0.1
port = 3493
poll_interval_seconds = 5
command_timeout_seconds = 3
command_username = legacy
command_password = legacy-secret
'''


def _draft():
    return UpsPolicyDraft(
        on_battery_delay_minutes=30,
        power_restore_delay_seconds=180,
    )


def test_managed_paths_include_nut_users_and_app_config():
    paths = ManagedNutPaths()

    assert paths.upsd_users == Path("/etc/nut/upsd.users")
    assert paths.app_config == Path("/etc/dh_pve_app/dh_pve_app.conf")


def test_rendered_identity_is_synchronized_and_preserves_unrelated_sections():
    target = render_managed_policy(
        _draft(),
        UPSMON,
        UPS_CONF,
        upsd_users_text=UPSD_USERS,
        app_config_text=APP_CONFIG,
        managed_password="existing-secret",
        command_script_path=Path(
            "/opt/digitalhouses/dh_pve_app/bin/dh-pve-ups-policy-cmd"
        ),
        ups_name="ups",
    )

    assert "[secondary]" in target.upsd_users_text
    assert "password = secondary-secret" in target.upsd_users_text
    assert target.upsd_users_text.count("[dh_primary_user]") == 1
    assert "password = existing-secret" in target.upsd_users_text
    assert "upsmon primary" in target.upsd_users_text
    assert "instcmds = ALL" in target.upsd_users_text

    assert (
        "MONITOR ups@127.0.0.1 1 dh_primary_user existing-secret primary"
        in target.upsmon_text
    )

    assert "[general]" in target.app_config_text
    assert "node_name = PVE" in target.app_config_text
    assert "[mqtt]" in target.app_config_text
    assert "host = 192.168.11.33" in target.app_config_text
    assert "command_username = dh_primary_user" in target.app_config_text
    assert "command_password = existing-secret" in target.app_config_text


def test_renderer_creates_managed_user_when_missing():
    target = render_managed_policy(
        _draft(),
        UPSMON,
        UPS_CONF,
        upsd_users_text="[secondary]\npassword = secondary-secret\nupsmon secondary\n",
        app_config_text=APP_CONFIG,
        managed_password="generated-secret",
        command_script_path=Path(
            "/opt/digitalhouses/dh_pve_app/bin/dh-pve-ups-policy-cmd"
        ),
        ups_name="ups",
    )

    assert "[dh_primary_user]" in target.upsd_users_text
    assert "password = generated-secret" in target.upsd_users_text
    assert "upsmon primary" in target.upsd_users_text
    assert "instcmds = ALL" in target.upsd_users_text
    assert "command_password = generated-secret" in target.app_config_text


def test_renderer_rejects_duplicate_managed_user_sections():
    duplicate = UPSD_USERS + "\n[dh_primary_user]\npassword = duplicate\n"

    with pytest.raises(PolicyApplyError, match="dh_primary_user"):
        render_managed_policy(
            _draft(),
            UPSMON,
            UPS_CONF,
            upsd_users_text=duplicate,
            app_config_text=APP_CONFIG,
            managed_password="existing-secret",
            command_script_path=Path(
                "/opt/digitalhouses/dh_pve_app/bin/dh-pve-ups-policy-cmd"
            ),
            ups_name="ups",
        )
