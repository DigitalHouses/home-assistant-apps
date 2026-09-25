import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'rootfs' / 'app'))

from config import load_config


def write_options(data):
    handle = tempfile.NamedTemporaryFile('w', delete=False, encoding='utf-8')
    json.dump(data, handle)
    handle.close()
    return Path(handle.name)


class StorageConfigTests(unittest.TestCase):
    def test_automatic_mariadb_supervisor_uses_supervisor_storage(self):
        path = write_options({
            'database_type': 'mariadb',
            'mariadb': {'connection': 'supervisor', 'database': 'homeassistant'},
            'storage': {'source': 'automatic'},
        })
        env = {
            'MYSQL_SERVICE_HOST': 'core-mariadb',
            'MYSQL_SERVICE_PORT': '3306',
            'MYSQL_SERVICE_USER': 'service',
            'MYSQL_SERVICE_PASSWORD': 'secret',
        }
        try:
            with patch.dict(os.environ, env, clear=False):
                cfg = load_config(path)
            self.assertEqual(cfg.storage.source, 'supervisor')
        finally:
            path.unlink(missing_ok=True)

    def test_automatic_external_database_without_ssh_credentials_is_disabled(self):
        path = write_options({
            'database_type': 'postgresql',
            'postgresql': {
                'host': '192.168.11.31', 'port': 5432, 'database': 'homeassistant',
                'username': 'hauser', 'password': 'hapass',
            },
            'storage': {'source': 'automatic'},
        })
        try:
            cfg = load_config(path)
            self.assertEqual(cfg.storage.source, 'disabled')
        finally:
            path.unlink(missing_ok=True)

    def test_explicit_ssh_uses_database_host_when_ssh_host_is_empty(self):
        path = write_options({
            'database_type': 'postgresql',
            'postgresql': {
                'host': '192.168.11.31', 'port': 5432, 'database': 'homeassistant',
                'username': 'hauser', 'password': 'hapass',
            },
            'storage': {
                'source': 'ssh', 'ssh_host': '', 'ssh_port': 22,
                'ssh_username': 'hauser', 'ssh_password': 'sshpass', 'path': '',
            },
        })
        try:
            cfg = load_config(path)
            self.assertEqual(cfg.storage.source, 'ssh')
            self.assertEqual(cfg.storage.host, '192.168.11.31')
            self.assertEqual(cfg.storage.username, 'hauser')
        finally:
            path.unlink(missing_ok=True)


if __name__ == '__main__':
    unittest.main()
