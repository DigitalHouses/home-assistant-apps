import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / 'rootfs' / 'app'
sys.path.insert(0, str(APP_DIR))

from config import DatabaseConfig


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
    'digitalhouses_db_monitoring_postgres_data_directory_test',
    'db/postgres.py',
    'psycopg2',
)
MARIADB_MODULE = load_adapter_module(
    'digitalhouses_db_monitoring_mariadb_data_directory_test',
    'db/mariadb.py',
    'pymysql',
)
PostgresAdapter = POSTGRES_MODULE.PostgresAdapter
MariaDBAdapter = MARIADB_MODULE.MariaDBAdapter


class DataDirectoryTests(unittest.TestCase):
    def test_postgres_data_directory_uses_show(self):
        adapter = PostgresAdapter(
            DatabaseConfig('postgresql', 'db', 5432, 'ha', 'u', 'p')
        )
        queries = []
        adapter._one = (
            lambda sql, params=(): queries.append(sql)
            or '/var/lib/postgresql/17/main'
        )
        self.assertEqual(
            adapter.data_directory(),
            '/var/lib/postgresql/17/main',
        )
        self.assertEqual(queries, ['SHOW data_directory'])

    def test_mariadb_data_directory_uses_server_variable(self):
        adapter = MariaDBAdapter(
            DatabaseConfig('mariadb', 'db', 3306, 'ha', 'u', 'p')
        )
        queries = []
        adapter._one = (
            lambda sql, params=(): queries.append(sql)
            or '/var/lib/mysql/'
        )
        self.assertEqual(adapter.data_directory(), '/var/lib/mysql/')
        self.assertEqual(queries, ['SELECT @@datadir'])


if __name__ == '__main__':
    unittest.main()
