from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "dh_pve_app"
VALIDATOR = ROOT / "scripts" / "validators" / "products" / "pve_agent.py"


def test_0515_version_and_repository_validator_contract():
    assert (APP / "VERSION").read_text(encoding="utf-8").strip() == "0.5.15"

    text = VALIDATOR.read_text(encoding="utf-8")
    for required in (
        'EXPECTED_VERSION = "0.5.15"',
        'app / "dh_app_pve.txt"',
        'ROOT_GUIDE="/root/dh_app_pve.txt"',
        'cat "${APP_DIR}/dh_app_pve.txt"',
        'rm -f -- "${ROOT_GUIDE}"',
    ):
        assert required in text


def test_0515_operational_guide_contract():
    guide = (APP / "dh_app_pve.txt").read_text(encoding="utf-8")

    for required in (
        "Установка",
        "Обновление",
        "systemctl status dh_pve_app",
        "/etc/dh_pve_app/dh_pve_app.conf",
        "--ups-policy-preflight",
        "/opt/digitalhouses/dh_pve_app/uninstall.sh",
        "--purge",
    ):
        assert required in guide


def test_0515_readme_and_changelog_document_installed_root_guide():
    readme = (APP / "README.md").read_text(encoding="utf-8")
    changelog = (APP / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "`VERSION` is `0.5.15`." in readme
    assert "/root/dh_app_pve.txt" in readme

    assert "## 0.5.9" in changelog
    assert "## 0.5.15" in changelog
    assert "## 0.5.14" in changelog
    assert "## 0.5.13" in changelog
    assert "## 0.5.9" in changelog
    assert "/root/dh_app_pve.txt" in changelog
    assert "version/source/commit" in changelog
    assert "value_appeared" in changelog
    assert "CPU usage" in changelog
    assert "tasklist" in changelog
    assert "STATIC" in changelog
    assert "unconfirmed" in changelog
    assert "tombstone" in changelog
    assert "binary_sensor.dh_app_pve_ups_configured" in changelog
    assert "ИБП не настроен" in changelog
