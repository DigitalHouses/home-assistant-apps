from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "digitalhouses_pve_agent"
VALIDATOR = ROOT / "scripts" / "validators" / "products" / "pve_agent.py"
DESIGN = (
    ROOT
    / "docs"
    / "digitalhouses_pve_agent"
    / "specs"
    / "2026-09-26-dh-pve-shutdown-history-runtime-facts-design.md"
)


def test_0525_version_and_repository_validator_contract():
    assert (APP / "VERSION").read_text(encoding="utf-8").strip() == "0.5.25"

    text = VALIDATOR.read_text(encoding="utf-8")
    assert 'EXPECTED_VERSION = "0.5.25"' in text


def test_0525_home_assistant_package_layout():
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


def test_0525_shutdown_runtime_contract_is_documented():
    readme = (APP / "README.md").read_text(encoding="utf-8")
    changelog = (APP / "CHANGELOG.md").read_text(encoding="utf-8")
    design = DESIGN.read_text(encoding="utf-8")

    assert "`VERSION` is `0.5.25`." in readme
    assert "## 0.5.25" in changelog
    assert "shutdown_status = correct | incorrect | unknown" in design
    assert "planned_shutdown_seconds" in design
    assert "planned_all_guest_shutdown_seconds" in design
    assert "shutdown_sequence" in design
    assert "standalone guest shutdown" in design.lower()
    assert "timeout_ratio = duration_seconds / timeout_seconds" in design
    assert "assessment:" in design
    assert "ok       -> clean and ratio < 0.80" in design
    assert "critical -> timeout/forced, or ratio >= 1.00" in design
    assert "Home Assistant is a presentation client" in design


def test_0525_operational_guide_contract():
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


def test_0525_installer_uses_canonical_source_and_legacy_runtime_identity():
    installer = (APP / "install.sh").read_text(encoding="utf-8")

    assert 'SOURCE_PRODUCT_DIR="digitalhouses_pve_agent"' in installer
    assert 'APP_NAME="dh_pve_app"' in installer
    assert 'SOURCE_APP="${tmp_dir}/repo/${SOURCE_PRODUCT_DIR}"' in installer
    assert 'APP_DIR="/opt/digitalhouses/${APP_NAME}"' in installer
