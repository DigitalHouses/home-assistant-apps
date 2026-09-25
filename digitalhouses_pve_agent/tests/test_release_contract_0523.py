from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "dh_pve_app"
VALIDATOR = ROOT / "scripts" / "validators" / "products" / "pve_agent.py"
DESIGN = (
    ROOT
    / "docs"
    / "digitalhouses_pve_agent"
    / "specs"
    / "2026-09-26-dh-pve-shutdown-history-runtime-facts-design.md"
)


def test_0523_version_and_repository_validator_contract():
    assert (APP / "VERSION").read_text(encoding="utf-8").strip() == "0.5.23"

    text = VALIDATOR.read_text(encoding="utf-8")
    assert 'EXPECTED_VERSION = "0.5.23"' in text


def test_0523_home_assistant_package_layout():
    packages = APP / "examples" / "packages"
    base = packages / "dh_app_pve_package.yaml"
    en = packages / "dh_app_pve_notification_local_package.yaml"
    ru = packages / "locales" / "ru" / "dh_app_pve_notification_local_package.yaml"

    assert base.is_file()
    assert en.is_file()
    assert ru.is_file()

    assert not (packages / "dh_app_pve_notification_package.yaml").exists()
    assert not (
        packages / "locales" / "ru" / "dh_app_pve_notification_package.yaml"
    ).exists()
    assert not (packages / "dh_app_pve_ui_package.yaml").exists()

    for notification in (en, ru):
        text = notification.read_text(encoding="utf-8")
        assert "trigger: event.received" in text
        assert "condition: trigger" in text
        assert "trigger.to_state.attributes" in text
        assert "event: dh_app_pve_notification" not in text
        assert "notification_schema_version" not in text
        assert "contract_error" not in text


def test_0523_shutdown_runtime_contract_is_documented():
    readme = (APP / "README.md").read_text(encoding="utf-8")
    changelog = (APP / "CHANGELOG.md").read_text(encoding="utf-8")
    design = DESIGN.read_text(encoding="utf-8")

    assert "`VERSION` is `0.5.23`." in readme
    assert "## 0.5.23" in changelog
    assert "shutdown_status = correct | incorrect | unknown" in design
    assert "planned_shutdown_seconds" in design
    assert "planned_all_guest_shutdown_seconds" in design
    assert "shutdown_sequence" in design
    assert "standalone guest shutdown" in design.lower()
    assert "Home Assistant is a presentation client" in design


def test_0523_operational_guide_contract():
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
