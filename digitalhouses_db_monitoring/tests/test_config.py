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


if __name__ == '__main__':
    unittest.main()
