import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DISCOVERY_SOURCE = ROOT / "rootfs/app/discovery.py"
CHANGELOG = ROOT / "CHANGELOG.md"
README = ROOT / "README.md"
CONFIG = ROOT / "config.yaml"
DOCKERFILE = ROOT / "Dockerfile"


class ReleaseContract014Tests(unittest.TestCase):
    def test_release_version_is_consistent(self):
        self.assertIn("version: 0.1.14", CONFIG.read_text(encoding="utf-8"))
        self.assertIn(
            'ARG BUILD_VERSION="0.1.14"',
            DOCKERFILE.read_text(encoding="utf-8"),
        )
        self.assertIn("## 0.1.14", CHANGELOG.read_text(encoding="utf-8"))
        self.assertIn(
            "Version 0.1.14 is the current stable production release.",
            README.read_text(encoding="utf-8"),
        )

    def test_gb_migration_forces_one_time_discovery_reset(self):
        discovery = DISCOVERY_SOURCE.read_text(encoding="utf-8")

        self.assertIn("DISCOVERY_SCHEMA_VERSION = 5", discovery)
        self.assertIn(
            "{{ (value_json.stored_bytes / 1000000000) | round(1) }}",
            discovery,
        )
        self.assertEqual(discovery.count('unit_of_measurement="GB"'), 2)
        self.assertNotIn('unit_of_measurement="GiB"', discovery)


if __name__ == "__main__":
    unittest.main()
