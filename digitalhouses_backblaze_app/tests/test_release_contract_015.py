import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DISCOVERY_SOURCE = ROOT / "rootfs/app/discovery.py"
CHANGELOG = ROOT / "CHANGELOG.md"
README = ROOT / "README.md"
CONFIG = ROOT / "config.yaml"
DOCKERFILE = ROOT / "Dockerfile"


class ReleaseContract015Tests(unittest.TestCase):
    def test_release_version_is_consistent(self):
        self.assertIn("version: 0.1.15", CONFIG.read_text(encoding="utf-8"))
        self.assertIn(
            'ARG BUILD_VERSION="0.1.15"',
            DOCKERFILE.read_text(encoding="utf-8"),
        )
        self.assertIn("## 0.1.15", CHANGELOG.read_text(encoding="utf-8"))
        self.assertIn(
            "Version 0.1.15 is the current stable production release.",
            README.read_text(encoding="utf-8"),
        )

    def test_storage_sensors_are_fixed_decimal_gb(self):
        discovery = DISCOVERY_SOURCE.read_text(encoding="utf-8")

        self.assertIn("DISCOVERY_SCHEMA_VERSION = 6", discovery)
        self.assertEqual(
            discovery.count(
                "{{ (value_json.stored_bytes / 1000000000) | round(1) }}"
            ),
            2,
        )
        self.assertEqual(discovery.count('unit_of_measurement="GB"'), 2)

        total_block = discovery.split('"total_used": _component(', 1)[1].split(
            '"bucket_count": _component(', 1
        )[0]
        bucket_block = discovery.split('components[f"{prefix}_used"] = _component(', 1)[1].split(
            'components[f"{prefix}_files"] = _component(', 1
        )[0]

        self.assertNotIn('device_class="data_size"', total_block)
        self.assertNotIn('device_class="data_size"', bucket_block)
        self.assertIn('state_class="measurement"', total_block)
        self.assertIn('state_class="measurement"', bucket_block)


if __name__ == "__main__":
    unittest.main()
