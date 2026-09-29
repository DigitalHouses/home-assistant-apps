from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "digitalhouses_pve_agent"
VALIDATOR = ROOT / "scripts" / "validators" / "products" / "pve_agent.py"


def test_0541_version_contract():
    assert (APP / "VERSION").read_text(encoding="utf-8").strip() == "0.5.41"

    validator = VALIDATOR.read_text(encoding="utf-8")
    assert 'EXPECTED_VERSION = "0.5.41"' in validator

    readme = (APP / "README.md").read_text(encoding="utf-8")
    changelog = (APP / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "Current source release: `VERSION` is `0.5.41`." in readme
    assert "## 0.5.41" in changelog


def test_0541_operational_docs_use_current_release_tag():
    for path in (
        APP / "README.md",
        APP / "digitalhouses_pve_agent.txt",
        APP / "hardware" / "beelink" / "README.md",
    ):
        text = path.read_text(encoding="utf-8")
        assert "digitalhouses_pve_agent-v0.5.41" in text


def test_0541_runtime_is_0536_plus_full_manual_refresh():
    topology = (APP / "app" / "topology.py").read_text(encoding="utf-8")
    main = (APP / "app" / "main.py").read_text(encoding="utf-8")
    scheduler = (APP / "app" / "scheduler.py").read_text(encoding="utf-8")
    topics = (APP / "app" / "topics.py").read_text(encoding="utf-8")
    mqtt = (APP / "app" / "mqtt_bridge.py").read_text(encoding="utf-8")
    discovery = (APP / "app" / "discovery.py").read_text(encoding="utf-8")

    for forbidden in (
        "_storage_recovery_pending",
        "on_storage_recovered",
        "QGA восстановлен",
        "passthrough storage recovery ожидает",
        "return bool(seen)",
    ):
        assert forbidden not in topology

    assert "request_run(" not in scheduler
    assert "restart_agent" not in topics
    assert "restart_agent" not in discovery
    assert "restart_requested" not in mqtt
    assert "restart_agent" not in mqtt
    assert "RESTART_EXIT_CODE" not in main
    assert "restart_requested" not in main

    manual_start = main.index("manual_refresh_collectors=(")
    manual_end = main.index("static_collectors=", manual_start)
    manual = main[manual_start:manual_end]
    for collector in (
        "topology",
        "guests",
        "host",
        "cpu",
        "memory",
        "storage",
        "fans",
        "smart",
        "disk_temperature",
        "gpu",
    ):
        assert f'"{collector}",' in manual
    assert manual.index('"topology",') < manual.index('"smart",')

    refresh_branch = mqtt[mqtt.index("if topic == self.topics.refresh:"):]
    refresh_branch = refresh_branch[: refresh_branch.index("if topic == self.topics.ups_scan:")]
    assert "self.refresh_requested.set()" in refresh_branch
    assert "self.ups_refresh_requested.set()" in refresh_branch


def test_0541_installer_still_does_not_clean_canonical_mqtt():
    installer = (APP / "install.sh").read_text(encoding="utf-8")
    uninstaller = (APP / "uninstall.sh").read_text(encoding="utf-8")

    assert "--uninstall-mqtt-cleanup" not in installer
    assert "--uninstall-mqtt-cleanup" in uninstaller
