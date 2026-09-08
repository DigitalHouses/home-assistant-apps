import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

APP_DIR = Path(__file__).resolve().parents[1] / 'rootfs' / 'app'
sys.path.insert(0, str(APP_DIR))


def load_adapter_module(module_name, relative_path, dependency_name):
    dependency = types.ModuleType(dependency_name)
    spec = importlib.util.spec_from_file_location(
        module_name,
        APP_DIR / relative_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f'Unable to load {relative_path}')
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {dependency_name: dependency}):
        spec.loader.exec_module(module)
    return module


POSTGRES_MODULE = load_adapter_module(
    'digitalhouses_db_monitoring_postgres_ranking_test',
    'db/postgres.py',
    'psycopg2',
)
MARIADB_MODULE = load_adapter_module(
    'digitalhouses_db_monitoring_mariadb_ranking_test',
    'db/mariadb.py',
    'pymysql',
)
PostgresAdapter = POSTGRES_MODULE.PostgresAdapter
MariaDBAdapter = MARIADB_MODULE.MariaDBAdapter


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
