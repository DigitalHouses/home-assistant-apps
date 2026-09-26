import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from validators.common import ValidationError, discover_applications, load_yaml
from validators.products.pve_agent import validate_digitalhouses_pve_agent


class PveAgentRepositoryContractTests(unittest.TestCase):
    def test_pve_is_discovered_by_application_marker(self):
        names = {path.name for path in discover_applications(ROOT)}
        self.assertIn("digitalhouses_pve_agent", names)
        self.assertNotIn("dh_pve_app", names)

    def test_pve_specific_validator_passes_current_contract(self):
        validate_digitalhouses_pve_agent(
            ROOT,
            ROOT / "digitalhouses_pve_agent",
            {
                "type": "linux_agent",
                "version": (ROOT / "digitalhouses_pve_agent/VERSION").read_text().strip(),
            },
        )

    def test_pve_shipped_ha_packages_are_valid_yaml(self):
        app = ROOT / "digitalhouses_pve_agent"
        for relative in (
            "examples/packages/dh_pve_agent_package.yaml",
            "examples/packages/dh_pve_agent_notification_local_package.yaml",
            "examples/packages/locales/ru/dh_pve_agent_notification_local_package.yaml",
        ):
            loaded = load_yaml(app / relative, ROOT)
            self.assertIsInstance(loaded, dict, relative)

        self.assertFalse(
            (app / "examples/packages/dh_pve_agent_ui_package.yaml").exists(),
            "PVE HA helpers must be consolidated into dh_pve_agent_package.yaml",
        )

    def test_pve_validator_rejects_wrong_release_version(self):
        with self.assertRaisesRegex(ValidationError, "release version"):
            validate_digitalhouses_pve_agent(
                ROOT,
                ROOT / "digitalhouses_pve_agent",
                {"type": "linux_agent", "version": "0.4.0"},
            )


if __name__ == "__main__":
    unittest.main()
