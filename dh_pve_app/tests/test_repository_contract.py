from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def test_required_root_files_exist():
    required = [
        "digitalhouses.app",
        "VERSION",
        "README.md",
        "CHANGELOG.md",
        "requirements.txt",
        "app/__init__.py",
        "examples/dh_pve_app.conf.example",
    ]
    missing = [name for name in required if not (ROOT / name).is_file()]
    assert not missing, f"missing required files: {missing}"


def test_public_identity_contract():
    assert (ROOT / "digitalhouses.app").read_text().strip() == "type = linux_agent"
    version = (ROOT / "VERSION").read_text().strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", version)
    assert version == "0.2.0-alpha"

    readme = (ROOT / "README.md").read_text()
    assert "DigitalHouses/Global/dh_pve_app" in readme
    assert "DH PVE" in readme
    assert "DH UPS" in readme
