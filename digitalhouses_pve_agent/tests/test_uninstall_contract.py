from pathlib import Path

ROOT = Path(__file__).parents[1]
UNINSTALLER = ROOT / "uninstall.sh"


def _text() -> str:
    assert UNINSTALLER.exists()
    return UNINSTALLER.read_text(encoding="utf-8")


def test_uninstaller_has_only_default_and_purge_modes_with_early_validation():
    text = _text()

    assert text.startswith("#!/usr/bin/env bash\nset -euo pipefail")
    assert "\\${" not in text
    assert 'if [[ "${EUID}" -ne 0 ]]' in text
    assert "command -v pveversion" in text
    assert "/etc/pve" in text
    assert '"--purge"' in text
    assert "Неизвестный аргумент" in text

    validation_pos = text.index("Неизвестный аргумент")
    stop_pos = text.index('systemctl stop "${SERVICE_NAME}"')
    cleanup_pos = text.index("--uninstall-mqtt-cleanup")
    remove_pos = text.index('rm -rf -- "${APP_DIR}"')
    assert validation_pos < stop_pos < cleanup_pos < remove_pos


def test_uninstaller_records_service_state_and_restores_active_service_on_cleanup_failure():
    text = _text()

    assert 'was_active=0' in text
    assert 'was_enabled=0' in text
    assert 'systemctl is-active --quiet "${SERVICE_NAME}"' in text
    assert 'systemctl is-enabled --quiet "${SERVICE_NAME}"' in text
    assert 'if [[ "${was_active}" -eq 1 ]]; then' in text
    assert 'systemctl start "${SERVICE_NAME}"' in text
    assert "MQTT cleanup не завершен" in text

    cleanup_pos = text.index("--uninstall-mqtt-cleanup")
    failure_pos = text.index("MQTT cleanup не завершен")
    remove_pos = text.index('rm -rf -- "${APP_DIR}"')
    assert cleanup_pos < failure_pos < remove_pos


def test_uninstaller_requires_disable_success_when_service_was_enabled():
    text = _text()

    assert 'if [[ "${was_enabled}" -eq 1 ]]; then' in text
    assert "не удалось отключить автозапуск" in text

    disable_pos = text.index('systemctl disable "${SERVICE_NAME}"')
    remove_pos = text.index('rm -rf -- "${APP_DIR}"')
    assert disable_pos < remove_pos


def test_uninstaller_preserves_config_state_by_default_and_purges_only_after_cleanup():
    text = _text()

    assert 'CONFIG_DIR="/etc/${APP_NAME}"' in text
    assert 'STATE_DIR="/var/lib/${APP_NAME}"' in text
    assert 'if [[ "${purge}" -eq 1 ]]; then' in text
    assert "Полное удаление: удаляю config/state" in text
    assert 'rm -rf -- "${CONFIG_DIR}" "${STATE_DIR}"' in text

    cleanup_pos = text.index("--uninstall-mqtt-cleanup")
    purge_pos = text.index('rm -rf -- "${CONFIG_DIR}" "${STATE_DIR}"')
    assert cleanup_pos < purge_pos


def test_uninstaller_uses_installed_python_cleanup_and_never_owns_nut_or_dependencies():
    text = _text()

    assert '"${APP_DIR}/.venv/bin/python"' in text
    assert "-m app.main" in text
    assert "--uninstall-mqtt-cleanup" in text
    assert 'systemctl disable "${SERVICE_NAME}"' in text
    assert 'systemctl daemon-reload' in text
    assert 'systemctl reset-failed "${SERVICE_NAME}"' in text

    lowered = text.lower()
    for forbidden in (
        "/etc/nut",
        "upsmon -c fsd",
        "upscmd",
        "load.off",
        "load.on",
        "apt-get remove",
        "apt remove",
        "apt purge",
        "haos",
        "mosquitto",
    ):
        assert forbidden not in lowered


def test_uninstaller_removes_root_operational_guide_only_after_mqtt_cleanup():
    text = _text()

    assert 'ROOT_GUIDE="/root/digitalhouses_pve_agent.txt"' in text
    assert 'rm -f -- "${ROOT_GUIDE}"' in text

    cleanup_pos = text.index("--uninstall-mqtt-cleanup")
    guide_remove_pos = text.index('rm -f -- "${ROOT_GUIDE}"')
    assert cleanup_pos < guide_remove_pos
