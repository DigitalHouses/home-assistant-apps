import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from validators.common import discover_applications, is_application_directory_name
from validators.apps.dh_pve_app import validate_dh_pve_app


class DhPveRepositoryContractTests(unittest.TestCase):
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
            {"type": "linux_agent", "version": "0.1.0"},
        )


if __name__ == "__main__":
    unittest.main()
