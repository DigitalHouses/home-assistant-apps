import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "rootfs" / "app"))

from config import parse_config


class ConfigTests(unittest.TestCase):
    def test_defaults(self):
        config = parse_config({
            "application_key_id": "key-id",
            "application_key": "secret",
        })
        self.assertEqual(config.refresh_interval_hours, 6)
        self.assertEqual(config.log_level, "info")

    def test_credentials_are_required(self):
        with self.assertRaises(ValueError):
            parse_config({"application_key_id": "", "application_key": ""})


if __name__ == "__main__":
    unittest.main()
