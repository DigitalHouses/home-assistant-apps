from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "dh_pve_app"
VALIDATOR = ROOT / "scripts" / "validators" / "products" / "pve_agent.py"


def test_0520_version_and_repository_validator_contract():
    assert (APP / "VERSION").read_text(encoding="utf-8").strip() == "0.5.20"

    text = VALIDATOR.read_text(encoding="utf-8")
    assert 'EXPECTED_VERSION = "0.5.20"' in text


def test_0520_home_assistant_package_layout():
    packages = APP / "examples" / "packages"
    base = packages / "dh_app_pve_package.yaml"
    en = packages / "dh_app_pve_notification_local_package.yaml"
    ru = packages / "locales" / "ru" / "dh_app_pve_notification_local_package.yaml"

    assert base.is_file()
    assert en.is_file()
    assert ru.is_file()

    assert not (packages / "dh_app_pve_notification_package.yaml").exists()
    assert not (packages / "locales" / "ru" / "dh_app_pve_notification_package.yaml").exists()
    assert not (packages / "dh_app_pve_ui_package.yaml").exists()

    for notification in (en, ru):
        text = notification.read_text(encoding="utf-8")
        assert "trigger: event.received" in text
        assert "condition: trigger" in text
        assert "trigger.to_state.attributes" in text
        assert "event: dh_app_pve_notification" not in text
        assert "notification_schema_version" not in text
        assert "contract_error" not in text


def test_0520_readme_and_changelog_document_simple_notifications():
    readme = (APP / "README.md").read_text(encoding="utf-8")
    changelog = (APP / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "`VERSION` is `0.5.20`." in readme
    assert "dh_app_pve_notification_local_package.yaml" in readme
    assert "line_power_lost" in readme
    assert "line_power_restored" in readme
    assert "boost_started" in readme
    assert "cpu_throttling_started" in readme
    assert "storage_usage_high" in readme
    assert "pve_problem_debounce_seconds" in readme
    assert "event-time assessment snapshot" in readme
    assert "trigger.id" in readme
    assert "direct action" in readme

    assert "## 0.5.20" in changelog
    assert "## 0.5.20" in changelog
    assert "problem_updated" in changelog
    assert "semantic start/recovery" in changelog
    assert "trigger.id" in changelog
    assert "Notification Envelope" in changelog  # historical 0.5.16 entry remains
    assert "/root/dh_app_pve.txt" in changelog


def test_0520_operational_guide_contract():
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
