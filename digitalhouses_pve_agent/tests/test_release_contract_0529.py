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


def test_0530_version_and_repository_validator_contract():
    assert (APP / "VERSION").read_text(encoding="utf-8").strip() == "0.5.30"

    text = VALIDATOR.read_text(encoding="utf-8")
    assert 'EXPECTED_VERSION = "0.5.30"' in text


def test_0530_home_assistant_package_layout():
    packages = APP / "examples" / "packages"
    base = packages / "dh_pve_agent_package.yaml"
    en = packages / "dh_pve_agent_notification_local_package.yaml"
    ru = packages / "locales" / "ru" / "dh_pve_agent_notification_local_package.yaml"

    assert base.is_file()
    assert en.is_file()
    assert ru.is_file()

    assert not (packages / "dh_pve_agent_notification_package.yaml").exists()
    assert not (
        packages / "locales" / "ru" / "dh_pve_agent_notification_package.yaml"
    ).exists()
    assert not (packages / "dh_pve_agent_ui_package.yaml").exists()

    for notification in (en, ru):
        text = notification.read_text(encoding="utf-8")
        assert "trigger: event.received" in text
        assert "condition: trigger" in text
        assert "trigger.to_state.attributes" in text
        assert "event: dh_pve_agent_notification" not in text
        assert "notification_schema_version" not in text
        assert "contract_error" not in text


def test_0530_shutdown_runtime_contract_is_documented():
    readme = (APP / "README.md").read_text(encoding="utf-8")
    changelog = (APP / "CHANGELOG.md").read_text(encoding="utf-8")
    design = DESIGN.read_text(encoding="utf-8")

    assert "`VERSION` is `0.5.30`." in readme
    assert "## 0.5.30" in changelog
    assert "shutdown_status = correct | incorrect | unknown" in design
    assert "planned_shutdown_seconds" in design
    assert "planned_all_guest_shutdown_seconds" in design
    assert "shutdown_sequence" in design
    assert "standalone guest shutdown" in design.lower()
    assert "timeout_ratio = duration_seconds / timeout_seconds" in design
    assert "assessment:" in design
    assert "ok       -> clean and ratio < 0.80" in design
    assert "critical -> timeout/forced, or ratio >= 1.00" in design
    assert "self-contained per-guest snapshot" in design
    assert "later rename or deletion does not change historical presentation" in design
    assert "may derive missing `timeout_ratio`" in design
    assert "`assessment`. It must not use the guest's current timeout" in design
    assert "Home Assistant is a presentation client" in design


def test_0530_operational_guide_contract():
    guide = (APP / "digitalhouses_pve_agent.txt").read_text(encoding="utf-8")
    for required in (
        "Установка",
        "Обновление",
        "systemctl status digitalhouses_pve_agent",
        "/etc/digitalhouses_pve_agent/digitalhouses_pve_agent.conf",
        "--ups-policy-preflight",
        "/opt/digitalhouses/digitalhouses_pve_agent/uninstall.sh",
        "--purge",
    ):
        assert required in guide


def test_0530_installer_uses_canonical_source_and_legacy_runtime_identity():
    installer = (APP / "install.sh").read_text(encoding="utf-8")

    assert 'PRODUCT_ID="digitalhouses_pve_agent"' in installer
    assert 'SOURCE_PRODUCT_DIR="${PRODUCT_ID}"' in installer
    assert 'APP_NAME="${PRODUCT_ID}"' in installer
    assert 'SOURCE_APP="${tmp_dir}/repo/${SOURCE_PRODUCT_DIR}"' in installer
    assert 'APP_DIR="/opt/digitalhouses/${PRODUCT_ID}"' in installer
    assert 'LEGACY_APP_NAME="dh_pve_app"' in installer
