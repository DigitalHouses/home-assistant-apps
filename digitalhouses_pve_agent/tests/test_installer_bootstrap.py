from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "install.sh"


def _installer_text() -> str:
    return INSTALLER.read_text(encoding="utf-8")


def test_installer_checks_python3_venv_package_not_only_venv_help():
    text = _installer_text()

    assert 'dpkg-query' in text
    assert 'python3-venv' in text
    assert 'python3 -m venv --help >/dev/null 2>&1 || need_apt=1' not in text


def test_installer_repairs_existing_venv_when_pip_is_missing():
    text = _installer_text()

    assert '"${APP_DIR}/.venv/bin/python" -m pip --version' in text
    assert 'python3 -m venv --clear "${APP_DIR}/.venv"' in text


def test_installer_uses_codeload_for_exact_commit_without_git_clone():
    text = _installer_text()

    assert '[[ "${SOURCE_REF}" =~ ^[0-9a-fA-F]{40}$ ]]' in text
    assert 'https://codeload.github.com/DigitalHouses/home-assistant-apps/tar.gz/${SOURCE_REF}' in text
    assert 'tar -xzf "${archive}" --strip-components=1 -C "${tmp_dir}/repo"' in text
    assert 'SOURCE_SHA="${SOURCE_REF}"' in text

def test_installer_confirms_mqtt_settings_before_writing_config():
    text = _installer_text()

    assert 'Проверьте параметры:' in text
    assert 'Всё верно? [y/N]:' in text
    assert 'Password: задан' in text
    assert 'Password: не задан' in text
    assert 'case "${confirm,,}" in' in text
    assert 'y|yes)' in text
    assert text.index('Всё верно? [y/N]:') < text.index('} >"${CONFIG_FILE}"')


def test_installer_validates_mqtt_port_range_and_reprompts():
    text = _installer_text()

    assert 'Некорректный MQTT port. Допустимый диапазон: 1-65535.' in text
    assert '[[ "${mqtt_port}" =~ ^[0-9]+$ ]]' in text
    assert 'mqtt_port >= 1 && mqtt_port <= 65535' in text
    assert 'Повторите ввод MQTT-параметров.' in text

