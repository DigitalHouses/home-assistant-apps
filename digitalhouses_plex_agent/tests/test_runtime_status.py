import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class RuntimeStatusTests(unittest.TestCase):
    def test_route_address_is_local_source_and_hostname_is_linux(self):
        from app.runtime_status import host_identity
        sock = MagicMock()
        sock.__enter__.return_value = sock
        sock.getsockname.return_value = ('192.168.10.25', 12345)
        with patch('app.runtime_status.socket.gethostname', return_value='plex-vm'), patch(
            'app.runtime_status.socket.getaddrinfo', return_value=[
                (socket.AF_INET, socket.SOCK_DGRAM, 17, '', ('192.168.10.2', 1883))
            ]
        ), patch('app.runtime_status.socket.socket', return_value=sock):
            self.assertEqual(host_identity('mqtt.example', 1883),
                             {'hostname': 'plex-vm', 'ip': '192.168.10.25'})
        sock.connect.assert_called_once_with(('192.168.10.2', 1883))

    def test_undetermined_route_reports_unknown(self):
        from app.runtime_status import host_identity
        with patch('app.runtime_status.socket.getaddrinfo', side_effect=OSError):
            self.assertEqual(host_identity('missing', 1883)['ip'], 'unknown')

    def test_atomic_status_cadence_transition_and_no_secrets(self):
        from app.runtime_status import RuntimeStatus
        from app.models import BuildInfo
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'status.json'
            writer = RuntimeStatus(path, BuildInfo('0.8.6', 'local', 'abc'))
            with patch('app.runtime_status.time.monotonic', return_value=1):
                writer.update({'state': 'MQTT_PAUSED'}, 'starting', {'hostname': 'vm', 'ip': 'unknown'})
            saved = json.loads(path.read_text())
            self.assertEqual(saved['mqtt']['state'], 'MQTT_PAUSED')
            self.assertEqual(saved['version'], '0.8.6')
            with patch('app.runtime_status.time.monotonic', return_value=2), patch.object(writer.store, 'save') as save:
                writer.update({'state': 'MQTT_PAUSED'}, 'starting', saved)
                save.assert_not_called()
                writer.update({'state': 'CONNECTED'}, 'ok', {'hostname': 'vm','ip':'unknown'})
                save.assert_called_once()

    def test_status_storage_failure_does_not_stop_monitor(self):
        from app.runtime_status import RuntimeStatus
        from app.models import BuildInfo
        with tempfile.TemporaryDirectory() as d:
            parent = Path(d) / 'not-a-directory'
            parent.write_text('blocker')
            writer = RuntimeStatus(parent / 'status.json', BuildInfo('0.8.6','local','abc'))
            with self.assertLogs('app.runtime_status', level='WARNING'):
                writer.update({'state':'MQTT_PAUSED'}, 'disabled', {})

    def test_network_address_change_refreshes_at_bounded_cadence(self):
        from app.runtime_status import HostIdentity
        with patch('app.runtime_status.host_identity', side_effect=[
            {'hostname':'vm','ip':'10.0.0.1'}, {'hostname':'vm','ip':'10.0.0.2'}
        ]) as resolve:
            identity = HostIdentity('mqtt', 1883)
            self.assertTrue(identity.refresh(now=0))
            self.assertFalse(identity.refresh(now=10))
            self.assertTrue(identity.refresh(now=60))
            self.assertEqual(identity.value['ip'], '10.0.0.2')
            self.assertEqual(resolve.call_count,2)

    def test_host_identity_uses_cache_until_network_change_or_reconnect(self):
        from app.runtime_status import HostIdentity
        with patch('app.runtime_status.host_identity', return_value={'hostname':'vm','ip':'10.0.0.1'}) as resolve:
            identity = HostIdentity('mqtt', 1883)
            identity.refresh(now=0)
            identity.refresh(now=10)
            self.assertEqual(resolve.call_count, 1)
            identity.refresh(now=11, force=True)
            self.assertEqual(resolve.call_count, 2)

class HostDiscoveryTests(unittest.TestCase):
    def test_host_sensors_use_existing_device_and_stable_entity_prefix(self):
        from app.config import load_config
        from app.discovery import build_discovery_payload, build_topics
        from app.models import BuildInfo
        with tempfile.TemporaryDirectory() as d:
            config_file = Path(d) / 'agent.conf'
            config_file.write_text('[mqtt]\nhost = mqtt\n')
            config = load_config(config_file)
            payload = build_discovery_payload(config, BuildInfo('0.8.6','local','abc'))
        topics = build_topics(config)
        for key in ('hostname', 'ip'):
            component = payload['components'][key]
            self.assertEqual(component['default_entity_id'], 'sensor.dh_plex_agent_' + key)
            self.assertEqual(component['unique_id'], topics.device_id + '_' + key)
            self.assertEqual(component['entity_category'], 'diagnostic')
            self.assertEqual(component['state_topic'], topics.state + '/host')
            self.assertEqual(component['availability'], [{'topic': topics.app_availability,
                 'payload_available':'online','payload_not_available':'offline'}])


class FreshPublicationTests(unittest.TestCase):
    def test_forced_snapshot_replaces_pending_values_before_retry(self):
        from digitalhouses_plex_agent.tests.test_grouped_runtime_contract import make_runtime, snapshot, api_payload
        runtime, bridge = make_runtime([0, 1, 2])
        bridge.failed_group = 'activity'
        runtime.publish_snapshot(snapshot(activity='old'), api_payload())
        self.assertIn('activity', runtime.pending_groups)
        bridge.groups.clear()
        bridge.failed_group = None
        runtime.publish_snapshot(snapshot(activity='fresh'), api_payload(), force=True)
        activities = [payload['activity'] for group, payload in bridge.groups if group == 'activity']
        self.assertEqual(activities, ['fresh'])


if __name__ == '__main__':
    unittest.main()
