from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = ROOT / "scripts" / "validators" / "apps" / "dh_pve_app.py"
WORKFLOW = ROOT / ".github" / "workflows" / "validate.yml"
RECORDER_PACKAGE = (
    ROOT / "dh_pve_app" / "examples" / "packages" / "dh_app_pve_package.yaml"
)


def test_repository_validator_covers_051_version_sensor_and_uninstall_contract():
    text = VALIDATOR.read_text(encoding="utf-8")

    for required in (
        'EXPECTED_VERSION = "0.5.1"',
        'app / "app/uninstall_cleanup.py"',
        'app / "uninstall.sh"',
        '"sensor.dh_app_pve_app_version"',
        '"--uninstall-mqtt-cleanup"',
        'chmod 0755 "${APP_DIR}/uninstall.sh"',
    ):
        assert required in text


def test_ci_shell_syntax_checks_installer_and_uninstaller():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "bash -n dh_pve_app/install.sh" in text
    assert "bash -n dh_pve_app/uninstall.sh" in text


def test_app_version_sensor_is_not_in_explicit_recorder_whitelist():
    text = RECORDER_PACKAGE.read_text(encoding="utf-8")

    assert "sensor.dh_app_pve_app_version" not in text


def test_051_readme_documents_version_sensor_and_supported_uninstall():
    readme = (ROOT / "dh_pve_app" / "README.md").read_text(encoding="utf-8")

    for required in (
        "`VERSION` is `0.5.1`.",
        "sensor.dh_app_pve_app_version",
        "/opt/digitalhouses/dh_pve_app/uninstall.sh",
        "uninstall.sh --purge",
        "/etc/dh_pve_app/",
        "/var/lib/dh_pve_app/",
        "MQTT Discovery",
        "MQTT cleanup",
        "NUT",
        "OS dependencies",
    ):
        assert required in readme


def test_051_changelog_records_version_sensor_and_uninstall():
    changelog = (ROOT / "dh_pve_app" / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "## 0.5.1" in changelog
    assert "sensor.dh_app_pve_app_version" in changelog
    assert "uninstall.sh" in changelog
    assert "--purge" in changelog
