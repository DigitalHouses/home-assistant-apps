from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_systemd_unit_uses_canonical_paths_and_root_is_documented():
    text = (ROOT / "systemd" / "digitalhouses_pve_agent.service").read_text()
    assert "User=root" in text
    assert "SMART" in text
    assert "WorkingDirectory=/opt/digitalhouses/digitalhouses_pve_agent" in text
    assert (
        "ExecStart=/opt/digitalhouses/digitalhouses_pve_agent/.venv/bin/python "
        "-m app.main --config /etc/digitalhouses_pve_agent/digitalhouses_pve_agent.conf "
        "--state-dir /var/lib/digitalhouses_pve_agent"
    ) in text
    assert "Restart=on-failure" in text


def test_installer_preserves_config_and_migrates_legacy_runtime():
    text = (ROOT / "install.sh").read_text()
    assert 'PRODUCT_ID="digitalhouses_pve_agent"' in text
    assert 'APP_DIR="/opt/digitalhouses/${PRODUCT_ID}"' in text
    assert 'CONFIG_FILE="${CONFIG_DIR}/${PRODUCT_ID}.conf"' in text
    assert 'STATE_DIR="/var/lib/${PRODUCT_ID}"' in text
    assert 'LEGACY_SERVICE_NAME="${LEGACY_APP_NAME}.service"' in text
    assert 'LEGACY_APP_NAME="dh_pve_app"' in text
    assert 'if [[ ! -f "${CONFIG_FILE}" ]]; then' in text
    assert "nano /etc/digitalhouses_pve_agent/digitalhouses_pve_agent.conf" in text
    assert "/etc/machine-id" in text
    for token in (
        "digitalhouses-proxmox-mqtt.sh",
        "/etc/cron.d/digitalhouses-proxmox-mqtt",
        "crontab -r",
    ):
        assert token not in text



def test_installer_uses_canonical_product_identity_and_explicit_legacy_bridge():
    text = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert 'PRODUCT_ID="digitalhouses_pve_agent"' in text
    assert 'APP_NAME="${PRODUCT_ID}"' in text
    assert 'SOURCE_PRODUCT_DIR="${PRODUCT_ID}"' in text
    assert 'SOURCE_APP="${tmp_dir}/repo/${SOURCE_PRODUCT_DIR}"'.replace("\\", "") in text

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


def test_installer_restores_uninstaller_executable_mode():
    installer_text = (ROOT / "install.sh").read_text(encoding="utf-8")

    assert 'chmod 0755 "${APP_DIR}/uninstall.sh"' in installer_text


def test_static_policy_helper_is_directly_executable_and_installer_restores_mode():
    helper = ROOT / "bin" / "digitalhouses-pve-agent-ups-policy-cmd"
    helper_text = helper.read_text(encoding="utf-8")
    installer_text = (ROOT / "install.sh").read_text(encoding="utf-8")

    assert helper.is_file()
    assert helper.stat().st_mode & 0o111
    assert helper_text.startswith("#!/")
    assert 'chmod 0755 "${APP_DIR}/bin/digitalhouses-pve-agent-ups-policy-cmd"' in installer_text


def test_installer_deploys_root_quick_reference_with_build_metadata():
    guide = ROOT / "digitalhouses_pve_agent.txt"
    installer_text = (ROOT / "install.sh").read_text(encoding="utf-8")

    assert guide.is_file()
    guide_text = guide.read_text(encoding="utf-8")
    for token in (
        "Установка",
        "Обновление",
        "systemctl status digitalhouses_pve_agent",
        "/etc/digitalhouses_pve_agent/digitalhouses_pve_agent.conf",
        "/opt/digitalhouses/digitalhouses_pve_agent/uninstall.sh",
        "--purge",
    ):
        assert token in guide_text

    assert 'ROOT_GUIDE="/root/digitalhouses_pve_agent.txt"' in installer_text
    assert 'cat "${APP_DIR}/digitalhouses_pve_agent.txt"' in installer_text
    assert "version = %s" in installer_text
    assert "source = %s" in installer_text
    assert "commit = %s" in installer_text
