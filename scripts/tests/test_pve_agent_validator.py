import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from validators.common import (
    ValidationError,
    discover_applications,
    is_application_directory_name,
    load_yaml,
)
from validators.products.pve_agent import validate_dh_pve_app


class PveAgentRepositoryContractTests(unittest.TestCase):
    def test_compact_dh_pve_name_is_explicitly_supported(self):
        self.assertTrue(is_application_directory_name("dh_pve_app"))
        self.assertTrue(is_application_directory_name("digitalhouses_example"))
        self.assertFalse(is_application_directory_name("dh_random_app"))

    def test_dh_pve_is_discovered_as_application(self):
        names = {path.name for path in discover_applications(ROOT)}
        self.assertIn("dh_pve_app", names)

    def test_dh_pve_specific_validator_passes_current_contract(self):
        validate_dh_pve_app(
            ROOT,
            ROOT / "dh_pve_app",
            {"type": "linux_agent", "version": "0.5.20"},
        )

    def test_dh_pve_shipped_ha_packages_are_valid_yaml(self):
        app = ROOT / "dh_pve_app"
        for relative in (
            "examples/packages/dh_app_pve_package.yaml",
            "examples/packages/dh_app_pve_notification_local_package.yaml",
            "examples/packages/locales/ru/dh_app_pve_notification_local_package.yaml",
        ):
            loaded = load_yaml(app / relative, ROOT)
            self.assertIsInstance(loaded, dict, relative)

        self.assertFalse(
            (app / "examples/packages/dh_app_pve_ui_package.yaml").exists(),
            "PVE HA helpers must be consolidated into dh_app_pve_package.yaml",
        )

    def test_dh_pve_validator_rejects_wrong_release_version(self):
        with self.assertRaisesRegex(ValidationError, "release version"):
            validate_dh_pve_app(
                ROOT,
                ROOT / "dh_pve_app",
                {"type": "linux_agent", "version": "0.4.0"},
            )


if __name__ == "__main__":
    unittest.main()
