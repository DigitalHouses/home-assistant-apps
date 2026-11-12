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

def test_installer_prepares_native_configuration_before_services():
    text = _installer_text()
    assert '-m app.install_config' in text
    assert text.index('-m app.install_config') < text.index('systemctl stop')
    assert '--commit "${PREPARED_CONFIG}" "${CONFIG_FILE}"' in text


def test_installer_uses_native_port_validation():
    from app.config import ConfigError
    from app.install_config import prepare
    import tempfile
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'config'
        path.write_text('[mqtt]\nhost=broker\n')
        for port in ('0', '65536', 'text'):
            try:
                prepare(path, ['mqtt_port=' + port], non_interactive=True)
            except ConfigError:
                pass
            else:
                raise AssertionError('invalid port accepted')
        assert path.read_text() == '[mqtt]\nhost=broker\n'
