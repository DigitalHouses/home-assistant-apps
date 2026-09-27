from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "digitalhouses_pve_agent"
VALIDATOR = ROOT / "scripts" / "validators" / "products" / "pve_agent.py"


def test_0533_version_contract():
    assert (APP / "VERSION").read_text(encoding="utf-8").strip() == "0.5.33"
    validator = VALIDATOR.read_text(encoding="utf-8")
    assert 'EXPECTED_VERSION = "0.5.33"' in validator

    readme = (APP / "README.md").read_text(encoding="utf-8")
    changelog = (APP / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "Current source release: `VERSION` is `0.5.33`." in readme
    assert "## 0.5.33" in changelog


def test_0533_operational_guide_is_release_tag_only_for_production():
    guide = (APP / "digitalhouses_pve_agent.txt").read_text(encoding="utf-8")

    assert "digitalhouses_pve_agent/digitalhouses_pve_agent.txt" in guide
    assert "TAG=digitalhouses_pve_agent-v0.5.33" in guide
    assert 'DIGITALHOUSES_SOURCE_REF="$TAG"' in guide
    assert "DIGITALHOUSES_INSTALL_MODE=development" in guide
    assert "REF=<branch-or-full-sha>" in guide

    for stale in (
        "Обычная установка из main",
        "<reviewed-ref-or-sha>",
        "<reviewed-sha>",
        "digitalhouses_pve_agent/dh_pve_agent.txt",
    ):
        assert stale not in guide


def test_0533_beelink_profile_is_release_tag_only_for_production():
    text = (APP / "hardware" / "beelink" / "README.md").read_text(encoding="utf-8")

    assert "TAG=digitalhouses_pve_agent-v0.5.33" in text
    assert "development/recovery" in text
    assert "REF=<branch-or-full-sha>" in text

    assert "<reviewed-ref-or-sha>" not in text
    assert "normal standalone use on a Beelink/AZW host" not in text


def test_0533_readme_uses_current_release_and_canonical_guide_path():
    readme = (APP / "README.md").read_text(encoding="utf-8")

    assert "TAG=digitalhouses_pve_agent-v0.5.33" in readme
    assert "digitalhouses_pve_agent/digitalhouses_pve_agent.txt" in readme

    assert "TAG=digitalhouses_pve_agent-v0.5.30" not in readme
    assert "digitalhouses_pve_agent/dh_pve_agent.txt" not in readme



def test_0533_identity_and_lifecycle_contract_is_documented():
    readme = (APP / "README.md").read_text(encoding="utf-8")
    changelog = (APP / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "one PVE Agent per Home Assistant instance" in readme
    assert "unique_id = <entity object_id>_id" in readme
    assert "sensor.dh_pve_agent_version" in readme
    assert "sensor.dh_pve_agent_started" in readme
    assert "sensor.dh_pve_agent_app_version" not in readme
    assert "sensor.dh_pve_agent_agent_started" not in readme

    for required in (
        "complete retained purge",
        "digitalhouses_proxmox_<instance_id>",
        "Discovery manifest",
        "QEMU Guest Agent",
    ):
        assert required in changelog
