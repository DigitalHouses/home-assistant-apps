from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_installer_restores_static_policy_helper_executable_mode():
    text = (ROOT / "install.sh").read_text(encoding="utf-8")

    assert 'chmod 0755 "${APP_DIR}/bin/dh-pve-ups-policy-cmd"' in text
