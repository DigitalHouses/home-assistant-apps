import json
import sys
import tempfile
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "rootfs" / "app"
sys.path.insert(0, str(APP))

from config import load_settings


class ConfigTests(unittest.TestCase):
    def test_defaults_and_bounds(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "options.json"
            path.write_text(
                json.dumps({
                    "application_key_id": "key-id",
                    "application_key": "secret",
                    "refresh_interval_hours": 99,
                    "telemetry_enabled": False,
                }),
                encoding="utf-8",
            )
            settings = load_settings(path)
            self.assertEqual(settings.refresh_interval_hours, 24)
            self.assertFalse(settings.telemetry_enabled)
            self.assertEqual(settings.application_key_id, "key-id")


if __name__ == "__main__":
    unittest.main()
