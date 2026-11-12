from datetime import datetime, timezone
import io
import json
from pathlib import Path
import runpy
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from app.runtime_status import HostIdentity, RuntimeStatus, host_identity, local_samples, read_status
from app.shutdown_discovery import build_shutdown_aware_pve_discovery_payload as build_discovery_payload
from app.app import DhPveRuntime
from test_discovery import _config, _identity

ROOT = Path(__file__).resolve().parents[1]


class LocalDiagnosticsTests(unittest.TestCase):
    def test_host_route_uses_local_source_and_bounded_lookup(self):
        with patch('app.runtime_status.socket.gethostname', return_value='real-linux'), patch('app.runtime_status.subprocess.run', return_value=SimpleNamespace(stdout='[{"prefsrc":"192.0.2.42"}]')) as run:
            self.assertEqual(host_identity('broker', 1883), {'hostname': 'real-linux', 'ip': '192.0.2.42'})
            self.assertEqual(run.call_args.kwargs['timeout'], 1.5)
            self.assertEqual(run.call_args.args[0][-1], 'broker')
        with patch('app.runtime_status.subprocess.run', side_effect=OSError):
            self.assertEqual(host_identity('broker', 1883)['ip'], 'unknown')

    def test_identity_refreshes_periodically_and_reconnect(self):
        tracker = HostIdentity('broker', 1883)
        with patch('app.runtime_status.host_identity', return_value={'hostname': 'linux', 'ip': '192.0.2.42'}) as query:
            self.assertTrue(tracker.refresh(now=0))
            self.assertFalse(tracker.refresh(now=30))
            self.assertFalse(tracker.refresh(now=31, force=True))
            self.assertEqual(query.call_count, 2)
            tracker.refresh(now=92)
            self.assertEqual(query.call_count, 3)

    def test_discovery_same_device_stable_existing_entities_and_no_recorder(self):
        payload = build_discovery_payload(_config(), _identity(), version='0.5.82')
        for name in ('hostname', 'ip'):
            component = payload['components'][name]
            self.assertEqual(component['default_entity_id'], 'sensor.dh_pve_agent_' + name)
            self.assertEqual(component['entity_category'], 'diagnostic')
            self.assertTrue(component['state_topic'].endswith('/host_identity'))
            self.assertNotIn('device', component)
        self.assertIn('system', payload['components'])
        self.assertIn('device', payload)
        recorder = (ROOT / 'examples/packages/dh_pve_agent_package.yaml').read_text().split('  logbook:')[0]
        self.assertNotIn('sensor.dh_pve_agent_hostname', recorder)
        self.assertNotIn('sensor.dh_pve_agent_ip', recorder)

    def test_status_atomic_bounded_whitelist_and_stale_disk_sample(self):
        now = datetime.now(timezone.utc).isoformat()
        state = SimpleNamespace(available=True, last_success=now, data={
            'passed-through': {'temperature_c': 45, 'available': False, 'last_success_at': '2000-01-01T00:00:00Z', 'health_state': 'HEALTHY', 'password': 'never serialize'},
        })
        runtime = SimpleNamespace(_subsystems={'smart': state}, _jsonable=DhPveRuntime._jsonable, problem_engine=None)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'status'
            writer = RuntimeStatus(path, SimpleNamespace(version='0.5.82', commit='abc'))
            with patch('app.runtime_status.os.fsync', side_effect=AssertionError('fsync')):
                writer.update({'state': 'DISCONNECTED'}, {'hostname': 'linux', 'ip': 'unknown'}, runtime, None)
                first = path.stat().st_mtime_ns
                writer.update({}, {}, runtime, None)
                self.assertEqual(first, path.stat().st_mtime_ns)
            data = json.loads(path.read_text())
            self.assertNotIn('never serialize', path.read_text())
            self.assertFalse(data['samples']['smart']['data']['passed-through']['fresh'])
            self.assertEqual(data['samples']['smart']['data']['passed-through']['temperature_c'], 45)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertFalse(list(Path(directory).glob('.status-*')))

    def test_updater_restores_cli_and_both_guides_with_modes(self):
        namespace = runpy.run_path(str(ROOT / 'bin/digitalhouses-pve-agent-update-runner'))
        scope = namespace['backup_files'].__globals__
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = {name: root / 'installed' / name for name in scope['FILES']}
            app, state = root / 'app', root / 'state'
            app.mkdir()
            state.mkdir()
            (app / 'VERSION').write_text('0.5.82')
            for name, path in files.items():
                path.parent.mkdir(exist_ok=True)
                path.write_text('old ' + name)
                path.chmod(0o750 if name == 'cli' else 0o600)
            values = {'ROOT': app, 'STATE': state, 'BACKUP': state / 'backup', 'FILES': files,
                      'CONFIG': files['config'], 'UNIT': files['service'], 'run': MagicMock()}
            with patch.dict(scope, values):
                namespace['backup_files']()
                for path in files.values():
                    path.write_text('new')
                    path.chmod(0o644)
                namespace['rollback'](restart=False)
                for name in ('cli', 'guide', 'legacy_guide'):
                    self.assertEqual(files[name].read_text(), 'old ' + name)
                    self.assertEqual(files[name].stat().st_mode & 0o777, 0o750 if name == 'cli' else 0o600)


if __name__ == '__main__':
    unittest.main()
