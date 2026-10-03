from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "digitalhouses_pve_agent"
VALIDATOR = ROOT / "scripts" / "validators" / "products" / "pve_agent.py"


def test_0545_version_contract():
    assert (APP / "VERSION").read_text(encoding="utf-8").strip() == "0.5.56"

    validator = VALIDATOR.read_text(encoding="utf-8")
    assert 'EXPECTED_VERSION = "0.5.56"' in validator

    readme = (APP / "README.md").read_text(encoding="utf-8")
    changelog = (APP / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "Current source release: `VERSION` is `0.5.56`." in readme
    assert "## 0.5.56" in changelog


def test_0545_operational_docs_use_current_release_tag():
    for path in (
        APP / "README.md",
        APP / "digitalhouses_pve_agent.txt",
        APP / "hardware" / "beelink" / "README.md",
    ):
        text = path.read_text(encoding="utf-8")
        assert "digitalhouses_pve_agent-v0.5.56" in text


def test_0545_keeps_0536_runtime_cleanup_and_full_manual_refresh():
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
    # Откат QGA-recovery остаётся в силе; независимая кнопка Restart восстановлена.
    assert 'restart_agent=f"{base}/restart"' in topics
    assert '"default_entity_id": "button.dh_pve_agent_restart_agent"' in discovery
    assert "self.restart_requested = threading.Event()" in mqtt
    assert "RESTART_EXIT_CODE = 75" in main
    assert "def _restart_denial_reason(" in main

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


def test_0545_operation_state_contract_is_agent_owned():
    operation = (APP / "app" / "operation_status.py").read_text(encoding="utf-8")
    app_runtime = (APP / "app" / "app.py").read_text(encoding="utf-8")
    ups_runtime = (APP / "app" / "ups_runtime.py").read_text(encoding="utf-8")
    main = (APP / "app" / "main.py").read_text(encoding="utf-8")
    mqtt = (APP / "app" / "mqtt_bridge.py").read_text(encoding="utf-8")
    discovery = (APP / "app" / "discovery.py").read_text(encoding="utf-8")
    ups_discovery = (APP / "app" / "discovery_ups.py").read_text(encoding="utf-8")

    assert 'frozenset({"idle", "updating", "error"})' in operation
    for field in ("started_at", "finished_at", "duration_seconds", "error"):
        assert f'"{field}"' in operation

    assert "refresh_in_progress" in mqtt
    assert "ups_refresh_in_progress" in mqtt
    assert "ups_scan_in_progress" in mqtt
    assert "publish_refresh_operation" in mqtt
    assert "publish_ups_refresh_operation" in mqtt
    assert "publish_ups_scan_operation" in mqtt

    dynamic_runtime = (APP / "app" / "runtime_dynamic.py").read_text(encoding="utf-8")
    assert 'refresh_publisher(operation_payload("idle"))' in dynamic_runtime

    assert 'operation_payload("updating"' in app_runtime
    assert "commit_ok = self._commit_manual_refresh(finished_at)" in app_runtime
    assert '"idle" if success else "error"' in app_runtime
    assert 'operation_payload("updating"' in ups_runtime
    assert '"idle" if ok else "error"' in ups_runtime
    assert "ups_scan_in_progress.set()" in main
    assert '"error" if outcome.error else "idle"' in main

    assert '"default_entity_id": "sensor.dh_pve_agent_refresh_state"' in discovery
    assert '"default_entity_id": "sensor.dh_pve_agent_ups_scan_state"' in discovery
    assert '"default_entity_id": "sensor.dh_pve_agent_ups_refresh_state"' in ups_discovery


def test_0545_ui_uses_operation_state_not_fake_timers():
    pve = (APP / "examples" / "dh_pve_agent_dashboard.yaml").read_text(encoding="utf-8")
    ups = (APP / "examples" / "dh_pve_agent_ups_dashboard.yaml").read_text(encoding="utf-8")

    assert "sensor.dh_pve_agent_refresh_state" in pve
    assert "sensor.dh_pve_agent_ups_refresh_state" in pve
    assert "Обновление…" in pve
    assert "background: var(--secondary-background-color)" in pve

    assert "sensor.dh_pve_agent_ups_refresh_state" in ups
    assert "sensor.dh_pve_agent_ups_scan_state" in ups
    assert "Обновление UPS…" in ups
    assert "Поиск UPS…" in ups
    assert "background: var(--secondary-background-color)" in ups

    for forbidden in ("delay:", "timer.", "input_boolean."):
        assert forbidden not in pve
        assert forbidden not in ups


def test_0545_global_refresh_stays_active_through_ups_followup():
    app_runtime = (APP / "app" / "app.py").read_text(encoding="utf-8")
    main = (APP / "app" / "main.py").read_text(encoding="utf-8")
    mqtt = (APP / "app" / "mqtt_bridge.py").read_text(encoding="utf-8")

    assert "self.manual_refresh_followup" in app_runtime
    assert "followup_ok = bool(self.manual_refresh_followup())" in app_runtime
    assert "commit_ok = self._commit_manual_refresh(finished_at)" in app_runtime
    assert "self.last_refresh = completed_at" in app_runtime
    assert '"follow-up refresh failed"' in app_runtime

    assert "def refresh_ups_after_pve()" in main
    assert "runtime.set_manual_refresh_followup(refresh_ups_after_pve)" in main
    assert "return ups_runtime.manual_refresh()" in main

    refresh_branch = mqtt[mqtt.index("if topic == self.topics.refresh:"):]
    refresh_branch = refresh_branch[:refresh_branch.index("if topic == self.topics.ups_scan:")]
    assert "self.refresh_requested.set()" in refresh_branch
    assert "self.ups_refresh_requested.set()" not in refresh_branch


def test_0545_installer_still_does_not_clean_canonical_mqtt():
    installer = (APP / "install.sh").read_text(encoding="utf-8")
    uninstaller = (APP / "uninstall.sh").read_text(encoding="utf-8")

    assert "--uninstall-mqtt-cleanup" not in installer
    assert "--uninstall-mqtt-cleanup" in uninstaller
