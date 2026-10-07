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
    'digitalhouses_recorder_app_postgres_period_test',
    'db/postgres.py',
    'psycopg2',
)
MARIADB_MODULE = load_adapter_module(
    'digitalhouses_recorder_app_mariadb_period_test',
    'db/mariadb.py',
    'pymysql',
)
PostgresAdapter = POSTGRES_MODULE.PostgresAdapter
MariaDBAdapter = MARIADB_MODULE.MariaDBAdapter


class PeriodAdapterTests(unittest.TestCase):
    def _exercise(self, adapter_class):
        adapter = adapter_class.__new__(adapter_class)
        row_calls = []
        one_calls = []

        adapter._rows = lambda sql, params=(): (
            row_calls.append((sql, params)) or [(7, 9, 11, 13)]
        )
        adapter._one = lambda sql, params=(): (
            one_calls.append((sql, params)) or 1024
        )

        result = adapter.medium_metrics(
            hour_cutoff=100.0,
            previous_hour_start=80.0,
            previous_hour_end=140.0,
            current_hour_start=140.0,
            today_start=120.0,
            period_end=200.0,
        )

        self.assertEqual(result['records_last_hour'], 7)
        self.assertEqual(result['records_previous_hour'], 9)
        self.assertEqual(result['records_current_hour'], 11)
        self.assertEqual(result['records_today'], 13)

        self.assertEqual(len(row_calls), 1)
        sql, params = row_calls[0]
        self.assertIn('SUM(CASE WHEN last_updated_ts >= %s', sql)
        self.assertIn('last_updated_ts < %s', sql)
        self.assertNotIn('AT TIME ZONE', sql)
        self.assertNotIn('CONVERT_TZ', sql)
        self.assertEqual(
            params,
            (
                100.0,
                200.0,
                80.0,
                140.0,
                140.0,
                200.0,
                120.0,
                200.0,
                80.0,
                200.0,
            ),
        )
        self.assertEqual(len(one_calls), 1)

    def test_postgresql_uses_epoch_bounded_period_aggregation(self):
        self._exercise(PostgresAdapter)

    def test_mariadb_uses_epoch_bounded_period_aggregation(self):
        self._exercise(MariaDBAdapter)


if __name__ == '__main__':
    unittest.main()
