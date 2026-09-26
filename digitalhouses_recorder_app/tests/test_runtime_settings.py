import json
import sys
import tempfile
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / 'rootfs' / 'app'
sys.path.insert(0, str(APP_DIR))

from runtime_settings import (
    DISK_USAGE_THRESHOLD_DEFAULT,
    RuntimeSettingError,
    load_disk_usage_threshold,
    save_disk_usage_threshold,
)


class RuntimeSettingsTests(unittest.TestCase):
    def test_missing_file_uses_explicit_product_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'runtime_settings.json'
            self.assertEqual(
                load_disk_usage_threshold(path),
                DISK_USAGE_THRESHOLD_DEFAULT,
            )

    def test_saved_threshold_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'runtime_settings.json'
            saved = save_disk_usage_threshold('73', path)
            loaded = load_disk_usage_threshold(path)

            self.assertEqual(saved, 73.0)
            self.assertEqual(loaded, 73.0)
            self.assertEqual(
                json.loads(path.read_text(encoding='utf-8')),
                {'disk_usage_threshold_percent': 73.0},
            )

    def test_invalid_persisted_state_is_not_silently_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'runtime_settings.json'
            path.write_text('{"disk_usage_threshold_percent": 0}\n', encoding='utf-8')

            with self.assertRaises(RuntimeSettingError):
                load_disk_usage_threshold(path)

    def test_invalid_command_value_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'runtime_settings.json'

            with self.assertRaises(RuntimeSettingError):
                save_disk_usage_threshold('101', path)


if __name__ == '__main__':
    unittest.main()
