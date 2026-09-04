import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'rootfs' / 'app'))

from storage import parse_df_output, parse_supervisor_host_payload


class StorageParsingTests(unittest.TestCase):
    def test_parse_df_output_returns_free_gb_and_capacity(self):
        output = (
            'Filesystem 1-blocks Used Available Capacity Mounted on\n'
            '/dev/mapper/pve-vm--101--disk--0 52521566208 11772088320 38048346112 24% /\n'
        )
        result = parse_df_output(output)
        self.assertEqual(result['db_disk_free'], 38.0)
        self.assertEqual(result['db_disk_used_percentage'], 24.0)

    def test_parse_supervisor_host_payload_returns_disk_metrics(self):
        payload = {
            'result': 'ok',
            'data': {'disk_free': 18.8, 'disk_total': 30.8, 'disk_used': 10.7},
        }
        result = parse_supervisor_host_payload(payload)
        self.assertEqual(result['db_disk_free'], 18.8)
        self.assertEqual(result['db_disk_used_percentage'], 34.7)


if __name__ == '__main__':
    unittest.main()

class FakeAdapter:
    def __init__(self, path='/var/lib/postgresql/17/main'):
        self.path = path
        self.calls = 0

    def data_directory(self):
        self.calls += 1
        return self.path


class FakeStorageConfig:
    def __init__(self, source, path=''):
        self.source = source
        self.host = '192.168.11.31'
        self.port = 22
        self.username = 'hauser'
        self.password = 'secret'
        self.path = path


class StorageCollectorTests(unittest.TestCase):
    def test_ssh_collector_detects_database_directory_once(self):
        from storage import StorageCollector

        adapter = FakeAdapter()
        seen_paths = []

        def ssh_fetcher(_config, path):
            seen_paths.append(path)
            return (
                'Filesystem 1-blocks Used Available Capacity Mounted on\n'
                '/dev/x 52521566208 11772088320 38048346112 24% /\n'
            )

        collector = StorageCollector(
            FakeStorageConfig('ssh'),
            adapter,
            ssh_fetcher=ssh_fetcher,
        )
        collector.collect()
        collector.collect()
        self.assertEqual(seen_paths, ['/var/lib/postgresql/17/main'] * 2)
        self.assertEqual(adapter.calls, 1)

    def test_supervisor_collector_uses_host_payload(self):
        from storage import StorageCollector

        collector = StorageCollector(
            FakeStorageConfig('supervisor'),
            FakeAdapter(),
            supervisor_fetcher=lambda: {
                'result': 'ok',
                'data': {'disk_free': 18.8, 'disk_total': 30.8, 'disk_used': 10.7},
            },
        )
        self.assertEqual(
            collector.collect(),
            {'db_disk_free': 18.8, 'db_disk_used_percentage': 34.7},
        )


class PermissionDeniedAdapter:
    def __init__(self):
        self.calls = 0

    def data_directory(self):
        self.calls += 1
        raise PermissionError('permission denied to examine data_directory')


class ManualPathAdapter:
    def __init__(self):
        self.calls = 0

    def data_directory(self):
        self.calls += 1
        raise AssertionError('data_directory must not be called for manual path')


class StoragePathResolutionTests(unittest.TestCase):
    def test_manual_path_has_priority_over_auto_detection(self):
        from storage import StorageCollector

        seen_paths = []
        detector_calls = []
        collector = StorageCollector(
            FakeStorageConfig('ssh', path='/srv/postgres'),
            ManualPathAdapter(),
            ssh_fetcher=lambda _config, path: seen_paths.append(path) or (
                'Filesystem 1-blocks Used Available Capacity Mounted on\n'
                '/dev/x 100 20 80 20% /srv/postgres\n'
            ),
            ssh_path_detector=lambda _config, _engine, _port: detector_calls.append(True) or '/',
        )

        collector.collect()
        self.assertEqual(seen_paths, ['/srv/postgres'])
        self.assertEqual(detector_calls, [])

    def test_permission_denied_from_database_falls_back_to_ssh_detection(self):
        from storage import StorageCollector

        adapter = PermissionDeniedAdapter()
        seen_paths = []
        collector = StorageCollector(
            FakeStorageConfig('ssh'),
            adapter,
            ssh_fetcher=lambda _config, path: seen_paths.append(path) or (
                'Filesystem 1-blocks Used Available Capacity Mounted on\n'
                '/dev/x 100 20 80 20% /\n'
            ),
            ssh_path_detector=lambda _config, engine, _port: (
                '/var/lib/postgresql/17/main' if engine == 'postgresql' else '/'
            ),
        )
        collector.adapter.config = type('DB', (), {'engine': 'postgresql'})()

        collector.collect()
        self.assertEqual(seen_paths, ['/var/lib/postgresql/17/main'])
        self.assertEqual(adapter.calls, 1)
        self.assertEqual(collector.resolved_path, '/var/lib/postgresql/17/main')

    def test_empty_ssh_detection_falls_back_to_root(self):
        from storage import StorageCollector

        adapter = PermissionDeniedAdapter()
        seen_paths = []
        collector = StorageCollector(
            FakeStorageConfig('ssh'),
            adapter,
            ssh_fetcher=lambda _config, path: seen_paths.append(path) or (
                'Filesystem 1-blocks Used Available Capacity Mounted on\n'
                '/dev/x 100 20 80 20% /\n'
            ),
            ssh_path_detector=lambda _config, _engine, _port: '',
        )
        collector.adapter.config = type('DB', (), {'engine': 'postgresql'})()

        collector.collect()
        self.assertEqual(seen_paths, ['/'])

class PostgresClusterSelectionTests(unittest.TestCase):
    def test_selects_online_cluster_matching_database_port(self):
        from storage import select_postgres_cluster_path

        output = (
            '16 main 5433 down postgres /var/lib/postgresql/16/main /var/log/postgresql/postgresql-16-main.log\n'
            '17 main 5432 online postgres /var/lib/postgresql/17/main /var/log/postgresql/postgresql-17-main.log\n'
        )
        self.assertEqual(
            select_postgres_cluster_path(output, 5432),
            '/var/lib/postgresql/17/main',
        )

    def test_ignores_down_cluster_even_when_port_matches(self):
        from storage import select_postgres_cluster_path

        output = (
            '16 main 5432 down postgres /var/lib/postgresql/16/main /var/log/postgresql/postgresql-16-main.log\n'
            '17 main 5433 online postgres /var/lib/postgresql/17/main /var/log/postgresql/postgresql-17-main.log\n'
        )
        self.assertEqual(select_postgres_cluster_path(output, 5432), '')
