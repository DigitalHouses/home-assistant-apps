from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "digitalhouses_pve_agent"


def test_0534_clean_reinstall_behavior_remains_historically_documented():
    changelog = (APP / "CHANGELOG.md").read_text(encoding="utf-8")
    section = changelog.split("## 0.5.34", 1)[1].split("## 0.5.33", 1)[0]

    assert "canonical clean-reinstall preflight" in section
    assert "installer runs the full current-instance MQTT uninstall cleanup" in section
    assert "0.5.32 -> clean reinstall gap" in section
