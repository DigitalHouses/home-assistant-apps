import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'rootfs' / 'app'))

from config import load_config


class ConfigTests(unittest.TestCase):
    def test_publish_interval_is_read_in_minutes(self):
        options = {
            'database_type': 'postgresql',
            'postgresql': {
                'host': '127.0.0.1',
                'port': 5432,
                'database': 'homeassistant',
                'username': 'hauser',
                'password': 'secret',
            },
            'publish_interval_minutes': 7,
            'recorder_stale_seconds': 300,
            'timezone': 'Asia/Almaty',
            'log_level': 'info',
        }
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', delete=False) as handle:
            json.dump(options, handle)
            path = Path(handle.name)
        try:
            config = load_config(path)
        finally:
            path.unlink(missing_ok=True)

        self.assertEqual(config.publish_interval_minutes, 7)
        self.assertFalse(config.telemetry_enabled)

    def test_telemetry_is_opt_in_and_boolean(self):
        base = {
            'database_type': 'postgresql',
            'postgresql': {
                'host': 'db.example.local',
                'port': 5432,
                'database': 'homeassistant',
                'username': 'recorder_monitor',
                'password': 'secret',
            },
        }

        enabled_options = dict(base)
        enabled_options['telemetry_enabled'] = True
        with tempfile.NamedTemporaryFile(
            'w',
            encoding='utf-8',
            delete=False,
        ) as handle:
            json.dump(enabled_options, handle)
            enabled_path = Path(handle.name)
        try:
            self.assertTrue(
                load_config(enabled_path).telemetry_enabled
            )
        finally:
            enabled_path.unlink(missing_ok=True)

        invalid_options = dict(base)
        invalid_options['telemetry_enabled'] = 'false'
        with tempfile.NamedTemporaryFile(
            'w',
            encoding='utf-8',
            delete=False,
        ) as handle:
            json.dump(invalid_options, handle)
            invalid_path = Path(handle.name)
        try:
            with self.assertRaises(ValueError):
                load_config(invalid_path)
        finally:
            invalid_path.unlink(missing_ok=True)


if __name__ == '__main__':
    unittest.main()
