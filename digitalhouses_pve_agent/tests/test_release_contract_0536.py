from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "digitalhouses_pve_agent"
VALIDATOR = ROOT / "scripts" / "validators" / "products" / "pve_agent.py"


def test_0536_version_contract():
    assert (APP / "VERSION").read_text(encoding="utf-8").strip() == "0.5.36"

    validator = VALIDATOR.read_text(encoding="utf-8")
    assert 'EXPECTED_VERSION = "0.5.36"' in validator

    readme = (APP / "README.md").read_text(encoding="utf-8")
    changelog = (APP / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "Current source release: `VERSION` is `0.5.36`." in readme
    assert "## 0.5.36" in changelog


def test_0536_operational_docs_use_current_release_tag():
    for path in (
        APP / "README.md",
        APP / "digitalhouses_pve_agent.txt",
        APP / "hardware" / "beelink" / "README.md",
    ):
        text = path.read_text(encoding="utf-8")
        assert "digitalhouses_pve_agent-v0.5.36" in text


def test_0536_usb_topology_contract_is_read_only_and_additive():
    guests = (APP / "app" / "collectors" / "guests.py").read_text(encoding="utf-8")
    topology = (APP / "app" / "topology.py").read_text(encoding="utf-8")
    production = (APP / "app" / "production_guest.py").read_text(encoding="utf-8")
    discovery = (APP / "app" / "discovery_guest.py").read_text(encoding="utf-8")
    dashboard = (APP / "examples" / "dh_pve_agent_dashboard_ru.yaml").read_text(
        encoding="utf-8"
    )

    for expected in (
        "def parse_usb_passthrough(",
        "def parse_udev_properties(",
        "def usb_display_name(",
    ):
        assert expected in guests

    for expected in (
        "def _scan_usb_inventory(",
        "def _build_usb_assignments(",
        "def _host_usb_devices(",
        "usb_sys_root: Path = Path(\"/sys/bus/usb/devices\")",
    ):
        assert expected in topology

    assert '"connection": "passthrough_usb"' in production
    assert '"connection": "host_usb"' in production
    assert 'key=f"host_usb_{slug}"' in discovery
    assert 'subject="host_usb"' in discovery
    assert "USB " in dashboard
    assert "set kind = 'PCI'" in dashboard
    assert "item.get('problem_id'" in dashboard
    assert "item.get('average')" in dashboard
    assert "item.get('threshold')" in dashboard
    assert "item.get('summary'" not in dashboard
    assert "item.get('details'" not in dashboard


def test_0536_installer_still_does_not_clean_canonical_mqtt():
    installer = (APP / "install.sh").read_text(encoding="utf-8")
    uninstaller = (APP / "uninstall.sh").read_text(encoding="utf-8")

    assert "--uninstall-mqtt-cleanup" not in installer
    assert "--uninstall-mqtt-cleanup" in uninstaller
