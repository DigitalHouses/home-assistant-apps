import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.state_store import StateStore
from app.discovery_lifecycle import DiscoveryLifecycle


def payload(**topics):
    return {'components': {key: {'platform': 'sensor', 'state_topic': topic,
                                 'unique_id': key} for key, topic in topics.items()}}


class LifecycleTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = StateStore(Path(self.tmp.name) / 'manifest.json')
        self.bridge = Mock()
        self.bridge.publish_discovery.return_value = True
        self.bridge.clear_discovery_state.return_value = True
        self.runtime = DiscoveryLifecycle(self.bridge, self.store, 'plex')

    def sync(self, data, now=0, **kwargs):
        return self.runtime.sync(data, now=now, confirmed=True, online=True, **kwargs)

    def test_restart_removal_tombstone_then_final_and_readd(self):
        first = payload(a='plex/state/a', b='plex/state/b')
        self.assertTrue(self.sync(first))
        self.runtime = DiscoveryLifecycle(self.bridge, self.store, 'plex')
        self.bridge.reset_mock()
        self.assertTrue(self.sync(payload(a='plex/state/a')))
        calls = self.bridge.set_discovery_payload.call_args_list
        self.assertEqual(calls[0].args[0]['components']['b'], {'platform': 'sensor'})
        self.assertEqual(calls[1].args[0], payload(a='plex/state/a'))
        self.bridge.clear_discovery_state.assert_called_once_with('plex/state/b')
        self.assertTrue(self.sync(first, now=10))
        self.assertIn('b', self.store.load()['components'])

    def test_shared_topic_and_foreign_topics_never_deleted(self):
        self.sync(payload(a='plex/state/shared', b='plex/state/shared',
                          foreign='other/state', availability='plex/availability'))
        self.sync(payload(a='plex/state/shared'), now=10)
        self.bridge.clear_discovery_state.assert_not_called()

    def test_failed_ack_rolls_back_and_retries_at_ten_seconds(self):
        self.sync(payload(a='plex/state/a'))
        previous = self.store.load()
        self.bridge.publish_discovery.return_value = False
        self.assertFalse(self.sync(payload(), now=1))
        self.assertEqual(self.store.load(), previous)
        count = self.bridge.publish_discovery.call_count
        self.assertFalse(self.sync(payload(), now=2))
        self.assertEqual(self.bridge.publish_discovery.call_count, count)
        self.bridge.publish_discovery.return_value = True
        self.assertTrue(self.sync(payload(), now=11))
        self.assertEqual(self.store.load()['components'], {})

    def test_no_change_no_write_and_periodic_recovery(self):
        data = payload(a='plex/state/a')
        self.sync(data)
        with __import__('unittest').mock.patch.object(self.store, 'save') as save:
            self.sync(data, now=10)
            save.assert_not_called()
        self.assertEqual(self.bridge.publish_discovery.call_count, 1)
        self.sync(data, now=1800)
        self.assertEqual(self.bridge.publish_discovery.call_count, 2)

    def test_unconfirmed_offline_and_invalid_manifest_fail_closed(self):
        data = payload(a='plex/state/a')
        self.assertFalse(self.runtime.sync(data, now=0, confirmed=False, online=True))
        self.assertFalse(self.runtime.sync(data, now=0, confirmed=True, online=False))
        self.store.path.write_text('{broken')
        runtime = DiscoveryLifecycle(self.bridge, self.store, 'plex')
        self.assertFalse(runtime.sync(data, now=0, confirmed=True, online=True))
        self.bridge.publish_discovery.assert_not_called()

    def test_final_failure_does_not_repeat_acknowledged_tombstone(self):
        self.sync(payload(a='plex/state/a'))
        self.bridge.publish_discovery.side_effect = [True, False, True]
        self.assertFalse(self.sync(payload(), now=1))
        self.assertTrue(self.sync(payload(), now=11))
        self.assertEqual(self.bridge.publish_discovery.call_count, 4)

    def test_persistence_failure_preserves_manifest(self):
        self.sync(payload(a='plex/state/a'))
        before = self.store.load()
        with __import__('unittest').mock.patch.object(self.store, 'save', side_effect=OSError()):
            self.assertFalse(self.sync(payload(), now=1))
        self.assertEqual(self.store.load(), before)

    def test_readd_during_pending_removal_preserves_retained_state(self):
        original = payload(a='plex/state/a')
        self.sync(original)
        self.bridge.publish_discovery.return_value = False
        self.assertFalse(self.sync(payload(), now=1))
        self.bridge.publish_discovery.return_value = True
        self.assertFalse(self.sync(original, now=11))
        self.bridge.clear_discovery_state.assert_not_called()
        self.assertTrue(self.sync(original, now=21))
        self.assertIn('a', self.store.load()['components'])

    def test_invalid_owned_references_fail_closed(self):
        for topic in ('plex-other/state/a', 'other/state/a', 'plex/availability',
                      'homeassistant/device/plex/config', 'plex/state/#'):
            self.store.save({'version': 1, 'components': {'old': {
                'platform': 'sensor', 'topics': [topic]}}})
            runtime = DiscoveryLifecycle(self.bridge, self.store, 'plex')
            self.assertFalse(runtime.sync(payload(), now=0, confirmed=True, online=True))
        self.bridge.publish_discovery.assert_not_called()
        self.bridge.clear_discovery_state.assert_not_called()

    def test_api_outage_does_not_commit_or_prune_manifest(self):
        self.sync(payload(a='plex/state/a'))
        before = self.store.load()
        self.bridge.reset_mock()
        self.assertFalse(self.runtime.sync(payload(), now=1800, confirmed=False, online=True, force=True))
        self.assertEqual(self.store.load(), before)
        self.bridge.publish_discovery.assert_not_called()
        self.assertTrue(self.sync(payload(a='plex/state/a'), now=1810))

    def test_delete_failure_retries_without_republishing_acknowledged_config(self):
        self.sync(payload(a='plex/state/a'))
        self.bridge.clear_discovery_state.return_value = False
        self.assertFalse(self.sync(payload(), now=1))
        before = self.bridge.publish_discovery.call_count
        self.bridge.clear_discovery_state.return_value = True
        self.assertTrue(self.sync(payload(), now=11))
        self.assertEqual(self.bridge.publish_discovery.call_count, before)
