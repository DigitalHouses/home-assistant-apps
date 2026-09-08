import sys
import types
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / 'rootfs' / 'app'
sys.path.insert(0, str(APP_DIR))

config = sys.modules.get('config') or types.ModuleType('config')
config.StorageConfig = object
sys.modules['config'] = config

db = sys.modules.get('db') or types.ModuleType('db')
db_base = types.ModuleType('db.base')
db_base.DatabaseAdapter = object
sys.modules['db'] = db
sys.modules['db.base'] = db_base
sys.modules.pop('storage', None)

from storage import parse_df_output, parse_supervisor_host_payload


class StorageMetricsTests(unittest.TestCase):
    def test_df_metrics_include_used_and_total_gb(self):
        output = (
            'Filesystem 1B-blocks Used Available Capacity Mounted on\n'
            '/dev/sda1 100000000000 40000000000 60000000000 40% /\n'
        )

        metrics = parse_df_output(output)

        self.assertEqual(metrics['db_disk_free'], 60.0)
        self.assertEqual(metrics['db_disk_used'], 40.0)
        self.assertEqual(metrics['db_disk_total'], 100.0)
        self.assertEqual(metrics['db_disk_used_percentage'], 40.0)

    def test_supervisor_metrics_include_used_and_total_gb(self):
        payload = {
            'result': 'ok',
            'data': {
                'disk_free': 60.0,
                'disk_used': 40.0,
                'disk_total': 100.0,
            },
        }

        metrics = parse_supervisor_host_payload(payload)

        self.assertEqual(metrics['db_disk_free'], 60.0)
        self.assertEqual(metrics['db_disk_used'], 40.0)
        self.assertEqual(metrics['db_disk_total'], 100.0)
        self.assertEqual(metrics['db_disk_used_percentage'], 40.0)


if __name__ == '__main__':
    unittest.main()
