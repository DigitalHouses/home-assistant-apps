import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import cli
from app.config import load_config


class NativeManagementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'agent.conf'
        self.path.write_text('# retained\n[mqtt]\nhost = broker\npassword = old\n\n[unknown]\ncustom = yes\n')
        self.path.chmod(0o640)

    def test_batch_alias_metadata_idempotence_and_one_restart(self):
        with patch.object(cli, 'service_info', return_value={'ActiveState': 'active'}), patch.object(cli, 'restart_service') as restart, patch.object(cli, 'guard_restart') as guard:
            self.assertTrue(cli.set_config(self.path, ['mqtt_ip=new', 'mqtt_port=1884']))
            self.assertFalse(cli.set_config(self.path, ['mqtt_host=new', 'mqtt_port=1884']))
            restart.assert_called_once()
            guard.assert_called_once()
        self.assertIn('# retained', self.path.read_text())
        self.assertIn('[unknown]\ncustom = yes', self.path.read_text())
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o640)

    def test_stdin_secret_refuses_echoing_tty(self):
        class TtyStream(io.StringIO):
            def isatty(self):
                return True
        with patch('sys.stdin', TtyStream('sensitive\n')):
            with self.assertRaisesRegex(ValueError, 'redirected'):
                cli.set_config(self.path, ['mqtt_password=-'])
        self.assertEqual(load_config(self.path).mqtt.password, 'old')

    def test_compact_human_readable_local_status(self):
        samples = {
            'cpu': {'available': True, 'last_success': '2026-11-12T00:00:00+00:00',
                    'data': {'temperature_c': 61.2, 'usage_percent': 18}},
            'memory': {'available': True, 'data': {'used_gib': 12, 'total_gib': 64, 'usage_percent': 19}},
            'disk_temperature': {'available': True, 'data': {
                'disk1': {'model': 'NVMe 1TB', 'temperature_c': 42, 'available': True, 'fresh': True},
                'disk2': {'model': 'HDD 4TB', 'temperature_c': 38, 'available': False, 'fresh': False}}},
            'fans': {'available': True, 'data': {'it87.2608/fan3': {'rpm': 3033}}},
            'ups': {'available': True, 'data': {'primary_status': 'OL', 'battery_charge_percent': 100,
                                             'runtime_seconds': 2400}},
        }
        with patch.object(cli, 'service_info', return_value={'ActiveState': 'active', 'SubState':'running'}), patch('app.runtime_status.host_identity', return_value={'hostname':'pve', 'ip':'192.0.2.42'}), patch('app.runtime_status.read_status', return_value=({'mqtt': {'state':'CONNECTED', 'last_ack':'now'}, 'samples':samples, 'ups_configured':True, 'updated_at':'2026-11-12T00:00:00+00:00'}, True)), patch('app.runtime_status.sample_live', return_value=True), contextlib.redirect_stdout(io.StringIO()) as output:
            cli.print_status(self.path)
        summary = output.getvalue()
        for expected in ('SYSTEM', 'MQTT', 'HARDWARE', 'DISKS', 'FANS', 'UPS', 'MONITORING',
                         '61.2°C', 'NVMe 1TB: 42.0°C', 'HDD 4TB: STALE/UNAVAILABLE', 'FAN 3: 3033 RPM'):
            self.assertIn(expected, summary)
        self.assertNotIn('{"', summary)

    def test_invalid_batch_no_partial_write(self):
        original = self.path.read_bytes()
        with self.assertRaises(ValueError):
            cli.set_config(self.path, ['mqtt_host=new', 'mqtt_port=0'])
        self.assertEqual(self.path.read_bytes(), original)

    def test_stopped_no_restart_and_prepare_no_systemctl(self):
        with patch.object(cli, 'service_info', return_value={'ActiveState': 'inactive'}), patch.object(cli, 'restart_service') as restart:
            cli.set_config(self.path, ['log_level=debug'])
            restart.assert_not_called()
        with patch.object(cli, 'service_info', side_effect=AssertionError('systemctl')):
            self.assertTrue(cli.set_config(self.path, ['mqtt_host=prepared'], prepare=True))

    def test_secrets_only_stdin_and_both_supported(self):
        for key in ('mqtt_password', 'ups_command_password', 'mqtt.password', 'ups.command_password'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                cli.set_config(self.path, [key + '=do-not-print'])
        with patch('sys.stdin', io.StringIO('mqtt secret\nups secret\n')):
            cli.set_config(self.path, ['mqtt_password=-', 'ups_command_password=-'], prepare=True)
        config = load_config(self.path)
        self.assertEqual(config.mqtt.password, 'mqtt secret')
        self.assertEqual(config.ups.command_password, 'ups secret')

    def test_restart_failure_rolls_back(self):
        original = self.path.read_bytes()
        with patch.object(cli, 'service_info', return_value={'ActiveState': 'active'}), patch.object(cli, 'guard_restart'), patch.object(cli, 'restart_service', side_effect=RuntimeError('failed')):
            with self.assertRaises(RuntimeError):
                cli.set_config(self.path, ['mqtt_port=1885'])
        self.assertEqual(original, self.path.read_bytes())

    def test_guard_failure_does_not_write(self):
        original = self.path.read_bytes()
        with patch.object(cli, 'service_info', return_value={'ActiveState': 'active'}), patch.object(cli, 'guard_restart', side_effect=RuntimeError('unsafe')):
            with self.assertRaises(RuntimeError):
                cli.set_config(self.path, ['mqtt_port=1885'])
        self.assertEqual(original, self.path.read_bytes())

    def test_all_native_fields_have_mapping(self):
        from dataclasses import fields
        config = load_config(self.path)
        for section in fields(config):
            for field in fields(getattr(config, section.name)):
                if (section.name, field.name) == ('ups', 'poll_interval_seconds'):
                    continue  # Explicitly ignored compatibility field, not configurable.
                self.assertIn((section.name, field.name), cli.KEYS.values())

    def test_duplicate_alias_rejected(self):
        with self.assertRaises(ValueError):
            cli.set_config(self.path, ['mqtt_ip=a', 'mqtt_host=b'])

    def test_status_stopped_snapshot_is_stale_and_no_secret(self):
        runtime = self.path.parent / 'runtime.json'
        runtime.write_text(json.dumps({'pid': 10, 'mqtt': {'state': 'CONNECTED'}, 'samples': {'cpu': {'last_success': '2000-01-01T00:00:00Z', 'available': True, 'data': {'temperature_c': 50}}}}))
        output = io.StringIO()
        with patch.object(cli, 'service_info', return_value={'ActiveState': 'inactive', 'MainPID': '0'}), patch('app.runtime_status.host_identity', return_value={'hostname': 'linux', 'ip': 'unknown'}), contextlib.redirect_stdout(output):
            cli.print_status(self.path, runtime)
        self.assertIn('stale', output.getvalue().lower())
        self.assertNotIn('MQTT: CONNECTED', output.getvalue())
        self.assertNotIn('password', output.getvalue())


if __name__ == '__main__':
    unittest.main()
