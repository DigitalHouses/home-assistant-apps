import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DISCOVERY_SOURCE = ROOT / "rootfs/app/discovery.py"
DASHBOARD = ROOT / "examples/lovelace/dh_app_backblaze_dashboard.yaml"
CHANGELOG = ROOT / "CHANGELOG.md"
README = ROOT / "README.md"
CONFIG = ROOT / "config.yaml"
DOCKERFILE = ROOT / "Dockerfile"


class ReleaseContract013Tests(unittest.TestCase):
    def test_013_release_is_documented(self):
        self.assertIn("## 0.1.13", CHANGELOG.read_text(encoding="utf-8"))
        self.assertIn("DigitalHouses Backblaze App", README.read_text(encoding="utf-8"))

    def test_storage_entities_use_decimal_gb_without_identity_changes(self):
        discovery = DISCOVERY_SOURCE.read_text(encoding="utf-8")

        self.assertIn('"sensor.dh_backblaze_storage_used"', discovery)
        self.assertIn('f"sensor.dh_backblaze_{slug}_used"', discovery)
        self.assertEqual(
            discovery.count(
                "{{ (value_json.stored_bytes / 1000000000) | round(1) }}"
            ),
            2,
        )
        self.assertEqual(discovery.count('unit_of_measurement="GB"'), 2)
        self.assertNotIn('unit_of_measurement="GiB"', discovery)
        self.assertNotIn("1073741824", discovery)

    def test_storage_tree_keeps_absolute_bytes_and_decimal_dashboard_units(self):
        dashboard = DASHBOARD.read_text(encoding="utf-8")

        self.assertIn("bucket.current_bytes", dashboard)
        self.assertIn("folder.current_bytes", dashboard)
        self.assertIn("1000000000", dashboard)
        self.assertIn("1000000", dashboard)
        self.assertIn("~ ' GB'", dashboard)
        self.assertIn("~ ' MB'", dashboard)
        self.assertIn("~ ' KB'", dashboard)
        self.assertNotIn("GiB", dashboard)


if __name__ == "__main__":
    unittest.main()
