import os
from pathlib import Path

from app.ups_policy import PolicySafetyFacts, UpsPolicyDraft
from app.ups_policy_apply import ManagedNutPaths, PolicyApplyError, UpsPolicyApplier


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


def _paths(tmp_path):
    return ManagedNutPaths(
        upsmon=tmp_path / "nut" / "upsmon.conf",
        upssched=tmp_path / "nut" / "upssched.conf",
        ups_conf=tmp_path / "nut" / "ups.conf",
        upsd_users=tmp_path / "nut" / "upsd.users",
        app_config=tmp_path / "app" / "dh_pve_app.conf",
        command_script=tmp_path / "bin" / "dh-pve-ups-policy-cmd",
        metadata=tmp_path / "state" / "policy.json",
    )


def _seed(paths, *, users=UPSD_USERS):
    paths.upsmon.parent.mkdir(parents=True, exist_ok=True)
    paths.app_config.parent.mkdir(parents=True, exist_ok=True)
    paths.command_script.parent.mkdir(parents=True, exist_ok=True)
    paths.metadata.parent.mkdir(parents=True, exist_ok=True)
    paths.upsmon.write_text(UPSMON, encoding="utf-8")
    paths.ups_conf.write_text(UPS_CONF, encoding="utf-8")
    paths.upsd_users.write_text(users, encoding="utf-8")
    paths.app_config.write_text(APP_CONFIG, encoding="utf-8")
    paths.command_script.write_text(HELPER, encoding="utf-8")
    paths.command_script.chmod(0o755)


class Runner:
    def __init__(self, events, *, fail_service=None, app_active=True):
        self.events = events
        self.fail_service = fail_service
        self.app_active = app_active

    def __call__(self, command, **kwargs):
        text = " ".join(command)
        self.events.append(text)
        if self.fail_service and self.fail_service in text:
            return type("Result", (), {"returncode": 1, "stdout": "", "stderr": "boom"})()
        if command[:3] == ["systemctl", "is-active", "nut-monitor.service"]:
            return type("Result", (), {"returncode": 3, "stdout": "inactive\n", "stderr": ""})()
        if command[:3] == ["systemctl", "is-enabled", "nut-monitor.service"]:
            return type("Result", (), {"returncode": 1, "stdout": "disabled\n", "stderr": ""})()
        if command[:3] == ["systemctl", "is-active", "nut-server.service"]:
            return type("Result", (), {"returncode": 0, "stdout": "active\n", "stderr": ""})()
        if command[:3] == ["systemctl", "is-enabled", "nut-server.service"]:
            return type("Result", (), {"returncode": 0, "stdout": "enabled\n", "stderr": ""})()
        if command[:3] == ["systemctl", "is-active", "dh_pve_app.service"]:
            state = "active\n" if self.app_active else "inactive\n"
            return type(
                "Result",
                (),
                {"returncode": 0 if self.app_active else 3, "stdout": state, "stderr": ""},
            )()
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()


def _applier(paths, events, **kwargs):
    return UpsPolicyApplier(
        paths=paths,
        ups_name="ups",
        runner=Runner(
            events,
            fail_service=kwargs.pop("fail_service", None),
            app_active=kwargs.pop("app_active", True),
        ),
        effective_restart_delay_reader=lambda: events.append("restore-delay") or 180,
        helper_expected_uid=os.getuid(),
        helper_expected_gid=os.getgid(),
        **kwargs,
    )


def test_apply_preserves_existing_primary_password_and_syncs_all_consumers(tmp_path):
    paths = _paths(tmp_path)
    _seed(paths)
    events = []

    def must_not_generate():
        raise AssertionError("existing password must be preserved")

    verified = []
    result = _applier(
        paths,
        events,
        secret_generator=must_not_generate,
        credential_verifier=lambda username, password: verified.append((username, password)),
    ).apply(_draft(), _facts())

    assert result.success is True
    assert verified == [("dh_primary_user", "existing-secret")]
    assert "password = existing-secret" in paths.upsd_users.read_text(encoding="utf-8")
    assert "instcmds = ALL" in paths.upsd_users.read_text(encoding="utf-8")
    assert "dh_primary_user existing-secret primary" in paths.upsmon.read_text(encoding="utf-8")
    app_text = paths.app_config.read_text(encoding="utf-8")
    assert "command_username = dh_primary_user" in app_text
    assert "command_password = existing-secret" in app_text


def test_apply_generates_secret_when_primary_user_is_missing(tmp_path):
    paths = _paths(tmp_path)
    _seed(paths, users="[secondary]\npassword = secondary-secret\nupsmon secondary\n")
    events = []
    verified = []

    result = _applier(
        paths,
        events,
        secret_generator=lambda: "generated-secret",
        credential_verifier=lambda username, password: verified.append((username, password)),
    ).apply(_draft(), _facts())

    assert result.success is True
    assert verified == [("dh_primary_user", "generated-secret")]
    assert "password = generated-secret" in paths.upsd_users.read_text(encoding="utf-8")
    assert "command_password = generated-secret" in paths.app_config.read_text(encoding="utf-8")


def test_apply_restarts_server_before_credential_verification_and_monitor(tmp_path):
    paths = _paths(tmp_path)
    _seed(paths)
    events = []

    def verify(username, password):
        events.append("credential-verifier")

    result = _applier(
        paths,
        events,
        secret_generator=lambda: "unused",
        credential_verifier=verify,
    ).apply(_draft(), _facts())

    assert result.success is True
    driver = events.index("systemctl restart nut-driver@ups.service")
    server = events.index("systemctl restart nut-server.service")
    verifier = events.index("credential-verifier")
    delay = events.index("restore-delay")
    monitor = events.index("systemctl enable --now nut-monitor.service")
    assert driver < server < verifier < delay < monitor


def test_apply_restarts_active_app_after_commissioned_config_is_ready(tmp_path):
    paths = _paths(tmp_path)
    _seed(paths, users="[secondary]\npassword = secondary-secret\nupsmon secondary\n")
    events = []

    result = _applier(
        paths,
        events,
        secret_generator=lambda: "generated-secret",
        credential_verifier=lambda username, password: None,
        app_active=True,
    ).apply(_draft(), _facts())

    assert result.success is True
    monitor = events.index("systemctl enable --now nut-monitor.service")
    app_restart = events.index("systemctl restart dh_pve_app.service")
    assert monitor < app_restart


def test_apply_does_not_start_app_that_was_inactive(tmp_path):
    paths = _paths(tmp_path)
    _seed(paths)
    events = []

    result = _applier(
        paths,
        events,
        secret_generator=lambda: "unused",
        credential_verifier=lambda username, password: None,
        app_active=False,
    ).apply(_draft(), _facts())

    assert result.success is True
    assert "systemctl restart dh_pve_app.service" not in events
    assert "systemctl start dh_pve_app.service" not in events


def test_apply_rolls_back_users_and_app_config_when_nut_server_restart_fails(tmp_path):
    paths = _paths(tmp_path)
    _seed(paths)
    before = {
        path: path.read_bytes()
        for path in (paths.upsmon, paths.ups_conf, paths.upsd_users, paths.app_config)
    }
    events = []

    result = _applier(
        paths,
        events,
        fail_service="systemctl restart nut-server.service",
        secret_generator=lambda: "unused",
        credential_verifier=lambda username, password: None,
    ).apply(_draft(), _facts())

    assert result.success is False
    for path, content in before.items():
        assert path.read_bytes() == content
    assert not paths.upssched.exists()
    assert not paths.metadata.exists()


def test_apply_rolls_back_and_redacts_secret_when_credential_verification_fails(tmp_path):
    paths = _paths(tmp_path)
    _seed(paths, users="[secondary]\npassword = secondary-secret\nupsmon secondary\n")
    before_users = paths.upsd_users.read_bytes()
    before_app = paths.app_config.read_bytes()
    events = []

    def fail_verify(username, password):
        raise PolicyApplyError(f"authentication failed for {password}")

    result = _applier(
        paths,
        events,
        secret_generator=lambda: "generated-secret",
        credential_verifier=fail_verify,
    ).apply(_draft(), _facts())

    assert result.success is False
    assert "generated-secret" not in result.message
    assert paths.upsd_users.read_bytes() == before_users
    assert paths.app_config.read_bytes() == before_app


def test_apply_restores_old_app_config_if_app_restart_fails(tmp_path):
    paths = _paths(tmp_path)
    _seed(paths, users="[secondary]\npassword = secondary-secret\nupsmon secondary\n")
    before_app = paths.app_config.read_bytes()
    events = []

    result = _applier(
        paths,
        events,
        fail_service="systemctl restart dh_pve_app.service",
        secret_generator=lambda: "generated-secret",
        credential_verifier=lambda username, password: None,
        app_active=True,
    ).apply(_draft(), _facts())

    assert result.success is False
    assert paths.app_config.read_bytes() == before_app
    assert events.count("systemctl restart dh_pve_app.service") >= 2
