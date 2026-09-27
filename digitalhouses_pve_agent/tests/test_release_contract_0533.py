from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "digitalhouses_pve_agent"


def test_0533_identity_release_remains_documented():
    changelog = (APP / "CHANGELOG.md").read_text(encoding="utf-8")

    section = changelog.split("## 0.5.33", 1)[1].split("## 0.5.32", 1)[0]
    for expected in (
        "unique_id = <entity object_id>_id",
        "sensor.dh_pve_agent_version",
        "sensor.dh_pve_agent_profile",
        "sensor.dh_pve_agent_started",
        "complete retained purge",
        "digitalhouses_proxmox_<instance_id>",
        "Discovery manifest",
        "QEMU Guest Agent",
    ):
        assert expected in section


def test_0533_deterministic_home_assistant_identity_remains_in_source():
    identity = (APP / "app" / "discovery_identity.py").read_text(encoding="utf-8")
    pve = (APP / "app" / "discovery_groups.py").read_text(encoding="utf-8")
    ups = (APP / "app" / "discovery_ups_groups.py").read_text(encoding="utf-8")
    readme = (APP / "README.md").read_text(encoding="utf-8")

    assert 'return f"{object_id}_id"' in identity
    assert "canonicalize_component_unique_ids(components)" in pve
    assert "canonicalize_component_unique_ids(raw_components)" in ups
    assert "one PVE Agent per Home Assistant instance" in readme

    for entity_id in (
        "sensor.dh_pve_agent_version",
        "sensor.dh_pve_agent_profile",
        "sensor.dh_pve_agent_started",
    ):
        assert entity_id in pve


def test_0533_full_uninstall_cleanup_contract_remains():
    cleanup = (APP / "app" / "uninstall_cleanup.py").read_text(encoding="utf-8")
    topics = (APP / "app" / "topics.py").read_text(encoding="utf-8")

    for expected in (
        'topic_filter = f"{topics.base}/#"',
        "machine_topics = sorted(retained_topics)",
        '(topics.discovery, "")',
        '(ups_topics.discovery, "")',
        "topics.legacy_discoveries",
        "ups_topics.legacy_discoveries",
    ):
        assert expected in cleanup

    assert "digitalhouses_proxmox_" in topics
