from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "digitalhouses_pve_agent"


def test_0535_changelog_preserves_uninstall_only_cleanup_release():
    readme = (APP / "README.md").read_text(encoding="utf-8")
    changelog = (APP / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "## 0.5.35" in changelog
    assert (
        "install/update/reinstall never clears the current canonical MQTT namespace"
        in readme
    )
    assert (
        "Canonical retained MQTT cleanup is owned exclusively by the supported uninstaller"
        in readme
    )


def test_0535_canonical_mqtt_cleanup_is_uninstall_only():
    installer = (APP / "install.sh").read_text(encoding="utf-8")
    uninstaller = (APP / "uninstall.sh").read_text(encoding="utf-8")

    assert "canonical_clean_reinstall" not in installer
    assert "--uninstall-mqtt-cleanup" not in installer
    assert "--uninstall-mqtt-cleanup" in uninstaller


def test_0535_uninstall_keeps_full_instance_cleanup_contract():
    cleanup = (APP / "app" / "uninstall_cleanup.py").read_text(encoding="utf-8")
    readme = (APP / "README.md").read_text(encoding="utf-8")

    for expected in (
        'topic_filter = f"{topics.base}/#"',
        "machine_topics = sorted(retained_topics)",
        '(topics.discovery, "")',
        '(ups_topics.discovery, "")',
        "topics.legacy_discoveries",
        "ups_topics.legacy_discoveries",
    ):
        assert expected in cleanup

    assert "DigitalHouses/Global/digitalhouses_pve_agent/<instance_id>/#" in readme
