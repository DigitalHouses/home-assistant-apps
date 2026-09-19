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
