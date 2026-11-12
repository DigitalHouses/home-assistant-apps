import sys
from pathlib import Path
from types import SimpleNamespace
import stat
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.library_storage import LibraryStorageRuntime, storage_id
from app.plex_api import LibraryInfo


def library(path, title='Movies'):
    return LibraryInfo('1', title, 'movie', 'video', 1, path=path)


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.patches = [patch('app.library_storage._library_path_is_directory', return_value=True),
                        patch('app.library_storage.os.path.ismount', side_effect=lambda p: p in ('/', '/media', '/other')),
                        patch('app.library_storage.os.statvfs', return_value=SimpleNamespace(f_blocks=100, f_bfree=30, f_bavail=20, f_frsize=1024**3))]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def test_system_root_is_explicit_and_not_media_fallback(self):
        root = storage_id('/')
        r = LibraryStorageRuntime()
        r.collect((library('/media/movies'), library('/media/music', 'Music')), now=0)
        self.assertEqual(len(r.payload), 2)  # System and one shared media mount.
        self.assertEqual(r.payload[root]['storage_display_name'], 'System')
        self.assertEqual(r.payload[root]['mountpoint'], '/')
        self.assertEqual(r.payload[root]['library_names'], [])
        self.assertEqual(r.payload[root]['available_gib'], 20)
        with patch('app.library_storage.os.path.ismount', side_effect=lambda p: p == '/'):
            r.collect((library('/media/movies'),), now=60, force=True)
        self.assertIsNone(r.payload[storage_id('/media')]['percent'])
        self.assertIsNotNone(r.payload[root]['percent'])

    def test_grouping_df_capacity_and_cadence(self):
        r = LibraryStorageRuntime()
        libs = (library('/media/movies'), library('/media/music', 'Music'))
        self.assertTrue(r.collect(libs, now=0))
        self.assertEqual(r.mounts, ('/', '/media'))
        v = r.payload[storage_id('/media')]
        self.assertEqual(v['library_names'], ['Movies', 'Music'])
        self.assertAlmostEqual(v['percent'], 70 / 90 * 100)
        self.assertEqual((v['used_gib'], v['available_gib'], v['total_gib']), (70, 20, 90))
        with patch('app.library_storage.os.statvfs') as stat:
            r.collect(libs, now=10)
            stat.assert_not_called()
            r.collect(libs, now=10, online=False, force=True)
            stat.assert_not_called()
        r.collect(libs + (library('/other/tv'),), now=11)
        self.assertEqual(r.mounts, ('/', '/media', '/other'))

    def test_missing_unmounted_error_and_zero(self):
        r = LibraryStorageRuntime()
        libs = (library('/media/movies'),)
        r.collect(libs, now=0)
        for target, kwargs in [('_library_path_is_directory', {'side_effect': FileNotFoundError('library path missing')}),
                               ('os.path.ismount', {'side_effect': lambda p: p == '/'}),
                               ('os.statvfs', {'side_effect': OSError('denied')}),
                               ('os.statvfs', {'return_value': SimpleNamespace(f_blocks=0, f_bfree=0, f_bavail=0, f_frsize=1)})]:
            with patch('app.library_storage.' + target, **kwargs):
                r.collect(libs, now=60, force=True)
                self.assertEqual(r.mounts, ('/', '/media'))
                self.assertIsNone(r.payload[storage_id('/media')]['percent'])

    def test_no_media_read_permission_still_reports_shared_mount(self):
        # Production VM: /serzhan-pool/media mode 2770, agent not in media_group.
        # Its child libraries raise EACCES, but statvfs on the mount succeeds.
        libs = (library('/media/movies'), library('/media/tvshows', 'TV'),
                library('/media/music', 'Music'))
        from app.library_storage import _library_path_is_directory
        with patch('app.library_storage.os.stat', side_effect=PermissionError('EACCES')):
            self.assertTrue(_library_path_is_directory('/media/movies'))
        r = LibraryStorageRuntime()
        self.assertTrue(r.collect(libs, now=0))
        self.assertEqual(r.mounts, ('/', '/media'))
        entry = r.payload[storage_id('/media')]
        self.assertAlmostEqual(entry['percent'], 70 / 90 * 100)
        self.assertEqual(entry['library_names'], ['Movies', 'Music', 'TV'])
        self.assertEqual(entry['available_gib'], 20)

    def test_retry_and_reconnect_use_fresh_state(self):
        r = LibraryStorageRuntime()
        libs = (library('/media/movies'),)
        r.collect(libs, now=0)
        sent = []
        def publish(group, payload):
            sent.append((group, payload))
            return len(sent) > 1
        self.assertFalse(r.publish(publish))
        with patch('app.library_storage.os.statvfs', side_effect=OSError()):
            r.collect(libs, now=1, force=True)
        self.assertTrue(r.publish(publish, force=True))
        self.assertIsNone(sent[-1][1][storage_id('/media')]['percent'])
        self.assertTrue(r.publish(publish))
        self.assertEqual(len(sent), 2)
        r.publish(publish, force=True)
        self.assertEqual(len(sent), 3)
        self.assertEqual(storage_id('/media'), storage_id('/media'))

    def test_missing_path_can_recover_and_removed_mounts_drop(self):
        r = LibraryStorageRuntime()
        libs = (library('/media/movies'),)
        with patch('app.library_storage._library_path_is_directory', side_effect=FileNotFoundError('library path missing')):
            r.collect(libs, now=0)
            self.assertIsNone(r.payload[storage_id('/media/movies')]['percent'])
        r.collect(libs, now=60)
        self.assertEqual(r.mounts, ('/', '/media'))
        r.collect((), now=61)
        self.assertEqual(set(r.payload), {storage_id('/')})

    def test_discovery_metadata_and_legacy_preservation(self):
        from tempfile import TemporaryDirectory
        from app.config import load_config
        from app.discovery import build_discovery_payload, build_topics
        from app.models import BuildInfo
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'agent.conf'
            path.write_text('[mqtt]\nhost = mqtt\n')
            config = load_config(path)
        build = BuildInfo('0.8.7', 'test', 'abcdef')
        legacy = build_discovery_payload(config, build)['components']
        key = 'library_storage_' + storage_id('/media') + '_percent_used'
        dynamic = build_discovery_payload(config, build, storage_mounts=('/media',))['components']
        self.assertEqual({k: v for k, v in dynamic.items() if k != key}, legacy)
        sensor = dynamic[key]
        self.assertEqual(sensor['default_entity_id'], 'sensor.dh_plex_agent_' + key)
        self.assertEqual(sensor['state_topic'], build_topics(config).state + '/library_storage')
        self.assertEqual(sensor['unit_of_measurement'], '%')
        self.assertIn("is number", sensor['availability'][1]['value_template'])
        self.assertEqual(build_discovery_payload(config, build)['components'], legacy)
        r = LibraryStorageRuntime()
        r.collect((library('/media/movies'),), now=0)
        entry = r.payload[storage_id('/media')]
        self.assertEqual(entry['plex_section'], 'library_storage')
        self.assertEqual(entry['source'], 'plex_library_storage_statvfs')
        self.assertEqual(entry['mountpoint'], '/media')

    def test_root_fallback_and_resolution_errors_are_unavailable(self):
        for target, kwargs in [('os.path.ismount', {'side_effect': lambda p: p == '/'}),
                               ('os.path.realpath', {'side_effect': OSError('denied')})]:
            with self.subTest(target=target), patch('app.library_storage.' + target, **kwargs):
                r = LibraryStorageRuntime()
                with patch('app.library_storage.os.statvfs', return_value=SimpleNamespace(f_blocks=100, f_bfree=30, f_bavail=20, f_frsize=1024**3)) as statvfs:
                    r.collect((library('/missing/movie'),), now=0)
                    statvfs.assert_called_once_with('/')
                self.assertIn('/', r.mounts)  # Explicit System volume, not media fallback.
                self.assertIsNone(r.payload[storage_id('/missing/movie')]['percent'])

    def test_unchanged_reconnect_failure_is_retried_and_manual_refresh_collects(self):
        r = LibraryStorageRuntime()
        libs = (library('/media/movie'),)
        r.collect(libs, now=0)
        from unittest.mock import Mock
        publish = Mock(return_value=True)
        r.publish(publish)
        publish.return_value = False
        self.assertFalse(r.publish(publish, force=True))
        publish.return_value = True
        self.assertTrue(r.publish(publish))
        self.assertEqual(publish.call_count, 3)
        with patch('app.library_storage.os.statvfs', return_value=SimpleNamespace(
                f_blocks=100, f_bfree=50, f_bavail=40, f_frsize=1024**3)) as stat:
            r.collect(libs, now=1, force=True)
            self.assertEqual(stat.call_count, 2)
            stat.assert_any_call('/')
            stat.assert_any_call('/media')
        self.assertTrue(r.publish(publish))
        self.assertEqual(publish.call_args.args[1][storage_id('/media')]['used_gib'], 50)
        before = r.payload.copy()
        r.collect((), now=100, online=False, force=True)
        self.assertEqual(r.payload, before)

    def test_mount_hash_is_independent_of_library_name_and_order(self):
        r = LibraryStorageRuntime()
        r.collect((library('/media/movies'), library('/media/music', 'Music')), now=0)
        keys = set(r.payload)
        r.collect((library('/media/music', 'Audio'), library('/media/movies', 'Films')), now=1)
        self.assertEqual(set(r.payload), keys)
        self.assertEqual(len(next(iter(keys))), 12)
        self.assertNotEqual(storage_id('/media'), storage_id('/other'))
