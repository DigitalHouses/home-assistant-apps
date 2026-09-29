from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "digitalhouses_pve_agent"
VALIDATOR = ROOT / "scripts" / "validators" / "products" / "pve_agent.py"


def test_0540_version_contract():
    assert (APP / "VERSION").read_text(encoding="utf-8").strip() == "0.5.40"

    validator = VALIDATOR.read_text(encoding="utf-8")
    assert 'EXPECTED_VERSION = "0.5.40"' in validator

    readme = (APP / "README.md").read_text(encoding="utf-8")
    changelog = (APP / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "Current source release: `VERSION` is `0.5.40`." in readme
    assert "## 0.5.40" in changelog


def test_0540_operational_docs_use_current_release_tag():
    for path in (
        APP / "README.md",
        APP / "digitalhouses_pve_agent.txt",
        APP / "hardware" / "beelink" / "README.md",
    ):
        text = path.read_text(encoding="utf-8")
        assert "digitalhouses_pve_agent-v0.5.40" in text


def test_0540_usb_topology_contract_is_read_only_and_additive():
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


def test_0540_installer_still_does_not_clean_canonical_mqtt():
    installer = (APP / "install.sh").read_text(encoding="utf-8")
    uninstaller = (APP / "uninstall.sh").read_text(encoding="utf-8")

    assert "--uninstall-mqtt-cleanup" not in installer
    assert "--uninstall-mqtt-cleanup" in uninstaller


def test_0540_manual_disk_recovery_and_restart_agent_contract():
    topology = (APP / "app" / "topology.py").read_text(encoding="utf-8")
    main = (APP / "app" / "main.py").read_text(encoding="utf-8")
    scheduler = (APP / "app" / "scheduler.py").read_text(encoding="utf-8")
    topics = (APP / "app" / "topics.py").read_text(encoding="utf-8")
    mqtt = (APP / "app" / "mqtt_bridge.py").read_text(encoding="utf-8")
    discovery = (APP / "app" / "discovery.py").read_text(encoding="utf-8")
    service = (APP / "systemd" / "digitalhouses_pve_agent.service").read_text(
        encoding="utf-8"
    )

    assert 'qga[guest_id] = self._qga_state(guest, config, force=True)' in topology
    assert 'self._probe_guest_storage(guest, devices, qga[guest_id])' in topology
    assert "_storage_recovery_pending" not in topology
    assert "on_storage_recovered" not in topology
    assert "request_run(" not in scheduler
    assert "on_storage_recovered" not in main
    manual_start = main.index("manual_refresh_collectors=(")
    manual_end = main.index("static_collectors=", manual_start)
    manual = main[manual_start:manual_end]
    assert '"topology",' in manual
    assert '"smart",' in manual
    assert '"disk_temperature",' in manual
    assert manual.index('"topology",') < manual.index('"smart",')
    assert manual.index('"smart",') < manual.index('"disk_temperature",')

    assert 'restart_agent=f"{base}/restart"' in topics
    assert "self.restart_requested = threading.Event()" in mqtt
    assert "client.subscribe(self.topics.restart_agent, qos=1)" in mqtt
    assert '"default_entity_id": "button.dh_pve_agent_restart_agent"' in discovery

    assert "RESTART_EXIT_CODE = 75" in main
    assert "bridge.restart_requested.is_set()" in main
    assert "return RESTART_EXIT_CODE if restart_requested else 0" in main
    assert "systemctl restart" not in main
    assert "Restart=on-failure" in service

