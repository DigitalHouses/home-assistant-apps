import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'rootfs' / 'app'))

from db.postgres import PostgresAdapter
from db.mariadb import MariaDBAdapter


class RankingAdapterTests(unittest.TestCase):
    def _exercise(self, adapter_class):
        adapter = adapter_class.__new__(adapter_class)
        calls = []
        adapter._rows = lambda sql, params=(): calls.append((sql, params)) or [
            ('sensor.alpha', 42),
            ('sensor.beta', 21),
        ]

        all_time = adapter.top_entities(None)
        recent = adapter.top_entities(1234.5)

        self.assertEqual(all_time[0], ('sensor.alpha', 42))
        self.assertIn('JOIN states_meta', calls[0][0])
        self.assertNotIn('last_updated_ts >=', calls[0][0])
        self.assertEqual(calls[0][1], ())
        self.assertIn('last_updated_ts >= %s', calls[1][0])
        self.assertEqual(calls[1][1], (1234.5,))
        self.assertIn('LIMIT 10', calls[1][0])

    def test_postgresql_top_entities_queries_states_meta(self):
        self._exercise(PostgresAdapter)

    def test_mariadb_top_entities_queries_states_meta(self):
        self._exercise(MariaDBAdapter)


if __name__ == '__main__':
    unittest.main()
