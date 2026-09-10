from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_systemd_unit_uses_canonical_paths_and_root_is_documented():
    text = (ROOT / "systemd" / "dh_pve_app.service").read_text()
    assert "User=root" in text
    assert "SMART" in text
    assert "WorkingDirectory=/opt/digitalhouses/dh_pve_app" in text
    assert (
        "ExecStart=/opt/digitalhouses/dh_pve_app/.venv/bin/python "
        "-m app.main --config /etc/dh_pve_app/dh_pve_app.conf "
        "--state-dir /var/lib/dh_pve_app"
    ) in text
    assert "Restart=on-failure" in text


def test_installer_preserves_phase1_legacy_agent_and_config():
    text = (ROOT / "install.sh").read_text()
    assert 'APP_DIR="/opt/digitalhouses/${APP_NAME}"' in text
    assert 'CONFIG_FILE="${CONFIG_DIR}/${APP_NAME}.conf"' in text
    assert 'STATE_DIR="/var/lib/${APP_NAME}"' in text
    assert 'if [[ ! -f "${CONFIG_FILE}" ]]; then' in text
    assert "nano /etc/dh_pve_app/dh_pve_app.conf" in text
    assert "/etc/machine-id" in text
    for token in (
        "digitalhouses-proxmox-mqtt.sh",
        "/etc/cron.d/digitalhouses-proxmox-mqtt",
        "crontab -r",
    ):
        assert token not in text


def test_installer_does_not_echo_mqtt_password_after_entry():
    text = (ROOT / "install.sh").read_text()
    assert 'read -r -s mqtt_password' in text
    tail = text.split('read -r -s mqtt_password', 1)[1]
    assert 'echo "${mqtt_password}"' not in tail
    assert 'printf "%s\\n" "${mqtt_password}"' not in tail


def test_installer_validates_proxmox_and_configuration_before_service_restart():
    text = (ROOT / "install.sh").read_text()
    assert "command -v pveversion" in text
    check_pos = text.index("--check-config")
    restart_pos = text.index('systemctl restart "${SERVICE_NAME}"')
    assert check_pos < restart_pos
