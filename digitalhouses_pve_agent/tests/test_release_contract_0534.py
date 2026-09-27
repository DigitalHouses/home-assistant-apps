from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "digitalhouses_pve_agent"
VALIDATOR = ROOT / "scripts" / "validators" / "products" / "pve_agent.py"


def test_0534_version_contract():
    assert (APP / "VERSION").read_text(encoding="utf-8").strip() == "0.5.34"

    validator = VALIDATOR.read_text(encoding="utf-8")
    assert 'EXPECTED_VERSION = "0.5.34"' in validator

    readme = (APP / "README.md").read_text(encoding="utf-8")
    changelog = (APP / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "Current source release: `VERSION` is `0.5.34`." in readme
    assert "## 0.5.34" in changelog


def test_0534_clean_reinstall_purges_retained_mqtt_before_service_start():
    installer = (APP / "install.sh").read_text(encoding="utf-8")

    detect = 'if [[ ! -d "${APP_DIR}" && -f "${CONFIG_FILE}" ]]; then'
    cleanup = "--uninstall-mqtt-cleanup"
    start = 'systemctl restart "${SERVICE_NAME}"'

    assert "canonical_clean_reinstall=0" in installer
    assert detect in installer
    assert cleanup in installer
    assert "retained MQTT canonical namespace не очищен" in installer
    assert 'rm -rf -- "${APP_DIR}"' in installer

    assert installer.index(detect) < installer.index(cleanup)
    assert installer.index(cleanup) < installer.index(start)


def test_0534_clean_reinstall_failure_preserves_saved_config_and_state():
    installer = (APP / "install.sh").read_text(encoding="utf-8")
    block = installer.split(
        'if [[ "${canonical_clean_reinstall}" -eq 1 && "${legacy_runtime_detected}" -eq 0 ]]; then',
        1,
    )[1].split('VERSION="$(tr -d', 1)[0]

    assert 'rm -rf -- "${APP_DIR}"' in block
    assert 'rm -rf -- "${CONFIG_DIR}"' not in block
    assert 'rm -rf -- "${STATE_DIR}"' not in block
    assert 'systemctl restart "${SERVICE_NAME}"' not in block


def test_0534_operational_docs_use_current_release_tag():
    for path in (
        APP / "README.md",
        APP / "digitalhouses_pve_agent.txt",
        APP / "hardware" / "beelink" / "README.md",
    ):
        text = path.read_text(encoding="utf-8")
        assert "digitalhouses_pve_agent-v0.5.34" in text
