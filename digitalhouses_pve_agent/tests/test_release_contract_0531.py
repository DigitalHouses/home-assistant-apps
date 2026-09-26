from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "digitalhouses_pve_agent"
VALIDATOR = ROOT / "scripts" / "validators" / "products" / "pve_agent.py"
APP_STANDARD = ROOT / "docs" / "standards" / "DIGITALHOUSES_APP_STANDARD.md"
EVENTS_STANDARD = ROOT / "docs" / "standards" / "EVENTS_AND_NOTIFICATIONS_STANDARD.md"


def test_0531_version_contract():
    assert (APP / "VERSION").read_text(encoding="utf-8").strip() == "0.5.31"

    validator = VALIDATOR.read_text(encoding="utf-8")
    assert 'EXPECTED_VERSION = "0.5.31"' in validator

    readme = (APP / "README.md").read_text(encoding="utf-8")
    changelog = (APP / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "Current source release: `VERSION` is `0.5.31`." in readme
    assert "## 0.5.31" in changelog


def test_0531_home_assistant_automation_aliases_are_canonical():
    packages = APP / "examples" / "packages"
    base = (packages / "dh_pve_agent_package.yaml").read_text(encoding="utf-8")
    notifications = (
        (packages / "dh_pve_agent_notification_local_package.yaml").read_text(encoding="utf-8"),
        (packages / "locales" / "ru" / "dh_pve_agent_notification_local_package.yaml").read_text(encoding="utf-8"),
    )

    for text in notifications:
        assert "alias: DH PVE Agent · Notifications" in text
        assert "alias: DH PVE · Notifications" not in text

    assert "alias: DH PVE Agent · Close UPS Trigger editor after successful Apply" in base
    assert "alias: DH PVE · Close UPS Trigger editor after successful Apply" not in base


def test_0531_shared_standards_use_canonical_pve_examples():
    app_standard = APP_STANDARD.read_text(encoding="utf-8")
    assert "sensor.dh_pve_agent_app_version" in app_standard
    assert "sensor.dh_pve_agent_agent_started" in app_standard
    assert "sensor.dh_app_pve_app_version" not in app_standard
    assert "sensor.dh_app_pve_agent_started" not in app_standard

    events = EVENTS_STANDARD.read_text(encoding="utf-8")
    section = events.split("## 7. Canonical Home Assistant pattern", 1)[1].split(
        "## 8. Trigger IDs", 1
    )[0]
    assert "id: dh_pve_agent_notifications" in section
    assert "alias: DH PVE Agent · Notifications" in section
    assert "event.dh_pve_agent_ups_diagnostic" in section
    assert "action: persistent_notification.create" in section
    assert "dh_app_pve" not in section
    assert "script.write2log" not in section
