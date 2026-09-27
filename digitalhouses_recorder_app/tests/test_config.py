import json
import sys
import tempfile
import unittest
from unittest.mock import patch
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
            'top_entities_limit': 17,
            'log_level': 'info',
        }
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', delete=False) as handle:
            json.dump(options, handle)
            path = Path(handle.name)
        try:
            with patch.dict('os.environ', {'TZ': 'Asia/Almaty'}):
                config = load_config(path)
        finally:
            path.unlink(missing_ok=True)

        self.assertEqual(config.publish_interval_minutes, 7)
        self.assertEqual(config.top_entities_limit, 17)
        self.assertEqual(config.timezone, 'Asia/Almaty')
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
            with patch.dict('os.environ', {'TZ': 'Asia/Almaty'}):
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
            with patch.dict('os.environ', {'TZ': 'Asia/Almaty'}):
                with self.assertRaises(ValueError):
                    load_config(invalid_path)
        finally:
            invalid_path.unlink(missing_ok=True)


    def test_top_entities_limit_defaults_to_10(self):
        options = {
            'database_type': 'postgresql',
            'postgresql': {
                'host': 'db.example.local',
                'port': 5432,
                'database': 'homeassistant',
                'username': 'recorder_monitor',
                'password': 'secret',
            },
        }
        with tempfile.NamedTemporaryFile(
            'w',
            encoding='utf-8',
            delete=False,
        ) as handle:
            json.dump(options, handle)
            path = Path(handle.name)
        try:
            with patch.dict('os.environ', {'TZ': 'Asia/Almaty'}):
                config = load_config(path)
        finally:
            path.unlink(missing_ok=True)

        self.assertEqual(config.top_entities_limit, 10)

    def test_timezone_must_come_from_supervisor_environment(self):
        options = {
            'database_type': 'postgresql',
            'postgresql': {
                'host': 'db.example.local',
                'port': 5432,
                'database': 'homeassistant',
                'username': 'recorder_monitor',
                'password': 'secret',
            },
            'timezone': 'Europe/London',
        }
        with tempfile.NamedTemporaryFile(
            'w',
            encoding='utf-8',
            delete=False,
        ) as handle:
            json.dump(options, handle)
            path = Path(handle.name)
        try:
            with patch.dict(
                'os.environ',
                {'TZ': 'Asia/Almaty'},
                clear=False,
            ):
                config = load_config(path)
        finally:
            path.unlink(missing_ok=True)

        self.assertEqual(config.timezone, 'Asia/Almaty')



if __name__ == '__main__':
    unittest.main()
