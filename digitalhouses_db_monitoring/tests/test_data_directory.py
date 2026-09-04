import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'rootfs' / 'app'))

sys.modules.setdefault('pymysql', types.SimpleNamespace())
sys.modules.setdefault('psycopg2', types.SimpleNamespace())

from config import DatabaseConfig
from db.mariadb import MariaDBAdapter
from db.postgres import PostgresAdapter


class DataDirectoryTests(unittest.TestCase):
    def test_postgres_data_directory_uses_show(self):
        adapter = PostgresAdapter(DatabaseConfig('postgresql', 'db', 5432, 'ha', 'u', 'p'))
        queries = []
        adapter._one = lambda sql, params=(): queries.append(sql) or '/var/lib/postgresql/17/main'
        self.assertEqual(adapter.data_directory(), '/var/lib/postgresql/17/main')
        self.assertEqual(queries, ['SHOW data_directory'])

    def test_mariadb_data_directory_uses_server_variable(self):
        adapter = MariaDBAdapter(DatabaseConfig('mariadb', 'db', 3306, 'ha', 'u', 'p'))
        queries = []
        adapter._one = lambda sql, params=(): queries.append(sql) or '/var/lib/mysql/'
        self.assertEqual(adapter.data_directory(), '/var/lib/mysql/')
        self.assertEqual(queries, ['SELECT @@datadir'])


if __name__ == '__main__':
    unittest.main()
