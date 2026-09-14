from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_readme_feature_deploy_uses_same_ref_for_installer_and_source():
    text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "DIGITALHOUSES_SOURCE_REF" in text
    assert "raw.githubusercontent.com/DigitalHouses/home-assistant-apps/<ref>/dh_pve_app/install.sh" in text
