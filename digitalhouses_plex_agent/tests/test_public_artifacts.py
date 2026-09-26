from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_FILES = (
    ROOT / "README.md",
    ROOT / "examples" / "digitalhouses_plex_agent.conf.example",
    ROOT / "examples" / "lovelace" / "plex-dashboard.yaml",
)


def test_public_examples_do_not_contain_site_private_dependencies():
    combined = "\n".join(path.read_text(encoding="utf-8") for path in PUBLIC_FILES)

    assert "script.write2log" not in combined
    assert "X-Plex-Token" not in combined
    assert "PLEX_TOKEN=" not in combined

    private_ipv4 = re.compile(
        r"(?<![0-9])(?:"
        r"10(?:\.\d{1,3}){3}|"
        r"192\.168(?:\.\d{1,3}){2}|"
        r"172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}"
        r")(?![0-9])"
    )
    assert private_ipv4.search(combined) is None

def test_readme_uses_canonical_entity_prefix():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "dh_plex_agent_agent_" not in readme
    assert "sensor.dh_plex_agent_*" in readme
    assert "binary_sensor.dh_plex_agent_*" in readme
    assert "button.dh_plex_agent_*" in readme
