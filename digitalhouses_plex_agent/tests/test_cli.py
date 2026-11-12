import contextlib
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
import warnings
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import cli
from app.config import load_config


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'agent.conf'
        self.original = '# keep this comment\n[mqtt]\nhost = broker\nport = 1883\ncustom = untouched\n'
        self.path.write_text(self.original)
        self.path.chmod(0o640)

    def test_all_native_fields_covered(self):
        self.assertEqual(len(set(cli.KEYS.values())), 21)
        self.assertEqual(cli.KEYS['mqtt_ip'], ('mqtt', 'host'))
        self.assertEqual(cli.KEYS['mqtt_host'], ('mqtt', 'host'))

    def test_invalid_batch_does_not_write_or_restart(self):
        with patch.object(cli, 'service_info') as service:
            with self.assertRaises(ValueError):
                cli.set_config(self.path, ['mqtt_ip=new', 'mqtt_port=0'])
        self.assertEqual(self.path.read_text(), self.original)
        service.assert_not_called()

    def test_cross_field_batch_and_comments_permissions(self):
        with patch.object(cli, 'service_info', return_value={'ActiveState': 'active'}), patch.object(cli, 'restart_service') as restart:
            self.assertTrue(cli.set_config(self.path, ['poll_interval=120', 'cpu_window=180', 'high_load_interval=120']))
        restart.assert_called_once_with()
        self.assertIn('# keep this comment', self.path.read_text())
        self.assertIn('custom = untouched', self.path.read_text())
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o640)
        self.assertEqual(load_config(self.path).general.poll_interval_seconds, 120)

    def test_unchanged_effective_defaults_no_restart(self):
        with patch.object(cli, 'service_info') as service, patch.object(cli, 'restart_service') as restart:
            self.assertFalse(cli.set_config(self.path, ['mqtt_port=01883', 'log_level=INFO']))
        self.assertEqual(self.path.read_text(), self.original)
        restart.assert_not_called()
        service.assert_not_called()

    def test_inactive_only_updates_config(self):
        with patch.object(cli, 'service_info', return_value={'ActiveState': 'inactive'}), patch.object(cli, 'restart_service') as restart:
            self.assertTrue(cli.set_config(self.path, ['mqtt_ip=new']))
        restart.assert_not_called()
        self.assertEqual(load_config(self.path).mqtt.host, 'new')

    def test_restart_failure_rolls_back_bytes_and_permissions(self):
        with patch.object(cli, 'service_info', return_value={'ActiveState': 'active'}), patch.object(cli, 'restart_service', side_effect=RuntimeError('failed')):
            with self.assertRaisesRegex(RuntimeError, 'rolled back'):
                cli.set_config(self.path, ['mqtt_ip=new'])
        self.assertEqual(self.path.read_text(), self.original)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o640)

    def test_password_reject_argument_and_safe_stdin(self):
        with self.assertRaisesRegex(ValueError, 'stdin|hidden'):
            cli.set_config(self.path, ['mqtt_password=secret'])
        with patch('sys.stdin', io.StringIO('safe#=secret\n')), patch.object(cli, 'service_info', return_value={'ActiveState': 'inactive'}):
            cli.set_config(self.path, ['mqtt_password=-'])
        self.assertEqual(load_config(self.path).mqtt.password, 'safe#=secret')

    def test_password_hidden_prompt_and_no_output(self):
        with patch.object(cli.sys.stdin, 'isatty', return_value=True), patch.object(cli.getpass, 'getpass', return_value='hidden'), patch.object(cli, 'service_info', return_value={'ActiveState': 'inactive'}):
            cli.set_config(self.path, ['mqtt_password'])
        self.assertEqual(load_config(self.path).mqtt.password, 'hidden')

    def test_getpass_cannot_fall_back_to_echoing_secret(self):
        def insecure_prompt(prompt):
            warnings.warn('Password input may be echoed', cli.getpass.GetPassWarning)
            return 'should-not-be-read'
        with patch.object(cli.sys.stdin, 'isatty', return_value=True), patch.object(cli.getpass, 'getpass', side_effect=insecure_prompt):
            with self.assertRaises(ValueError):
                cli.set_config(self.path, ['mqtt_password'])
        self.assertEqual(self.path.read_text(), self.original)

    def test_duplicate_alias_and_newline_and_nonfinite_rejected(self):
        for pairs in (['mqtt_ip=a', 'mqtt_host=b'], ['mqtt_ip=a\nport=22'], ['cpu_change_threshold=nan'], ['high_load_threshold=inf']):
            with self.subTest(pairs=pairs), self.assertRaises(ValueError):
                cli.set_config(self.path, pairs)
        self.assertEqual(self.path.read_text(), self.original)

    def test_status_stopped_stale_connected_never_shown_as_live(self):
        runtime = self.path.parent / 'runtime_status.json'
        runtime.write_text(json.dumps({'pid': os.getpid(), 'updated_at': '2026-01-01T00:00:00+00:00', 'mqtt': {'state': 'CONNECTED'}, 'plex_api_status': 'ok'}))
        with patch.object(cli, 'service_info', return_value={'ActiveState': 'inactive', 'MainPID': '0'}), contextlib.redirect_stdout(io.StringIO()) as output:
            cli.print_status(self.path, runtime)
        text = output.getvalue()
        self.assertIn('stale', text.lower())
        self.assertIn('MQTT: UNKNOWN', text)
        self.assertNotIn('MQTT: CONNECTED', text)

    def test_every_key_can_be_set_and_repeated_idempotently(self):
        values = {
            'instance_id': 'plex_test', 'instance_name': 'Friendly agent',
            'poll_interval': '12', 'cpu_window': '120', 'log_level': 'debug',
            'telemetry_enabled': 'true', 'cpu_change_threshold': '3',
            'high_load_threshold': '85', 'high_load_interval': '120',
            'plex_api_enabled': 'false', 'plex_api_url': 'http://localhost:32400',
            'plex_api_token_file': '/etc/token', 'plex_api_timeout': '4',
            'library_refresh': '7200', 'mqtt_ip': 'new-broker', 'mqtt_host': 'other-broker',
            'mqtt_port': '1884', 'mqtt_username': 'user', 'mqtt_password': '-',
            'mqtt_topic_prefix': 'test/agent', 'mqtt_discovery_prefix': 'ha', 'mqtt_keepalive': '120',
        }
        with patch.object(cli, 'service_info', return_value={'ActiveState': 'inactive'}):
            for key, value in values.items():
                with self.subTest(key=key), patch('sys.stdin', io.StringIO('secret\n')):
                    self.assertTrue(cli.set_config(self.path, [f'{key}={value}']))
                with self.subTest(key=key), patch('sys.stdin', io.StringIO('secret\n')):
                    self.assertFalse(cli.set_config(self.path, [f'{key}={value}']))

    def test_invalid_cross_field_batch_has_no_partial_write(self):
        with self.assertRaises(ValueError):
            cli.set_config(self.path, ['mqtt_host=new', 'poll_interval=120'])
        self.assertEqual(self.path.read_text(), self.original)

    def test_full_line_comments_and_multiline_unrelated_values_preserved(self):
        self.path.write_text('# header\n[mqtt]\nhost: old\n    continuation\n; comment\ncustom = line1\n    line2\nport=1883\n')
        with patch.object(cli, 'service_info', return_value={'ActiveState': 'inactive'}):
            cli.set_config(self.path, ['mqtt_host=new'])
        self.assertEqual(self.path.read_text(), '# header\n[mqtt]\nhost: new\n; comment\ncustom = line1\n    line2\nport=1883\n')

    def test_status_live_paused_and_stale_pid_or_start(self):
        runtime = self.path.parent / 'runtime_status.json'
        now, mono = time.time(), time.monotonic()
        runtime.write_text(json.dumps({
            'pid': 123, 'updated_at': datetime.fromtimestamp(now, timezone.utc).isoformat(),
            'mqtt': {'state': 'MQTT_PAUSED', 'last_ack': 'ack-time'}, 'plex_api_status': 'ok',
        }))
        service = {'ActiveState': 'active', 'SubState': 'running', 'MainPID': '123',
                   'ActiveEnterTimestampMonotonic': str(int((mono - 30) * 1e6)),
                   'ExecMainStartTimestampMonotonic': str(int((mono - 30) * 1e6))}
        with patch('app.runtime_status.host_identity', return_value={'hostname': 'linux', 'ip': '192.0.2.2'}), patch.object(cli, 'service_info', return_value=service), contextlib.redirect_stdout(io.StringIO()) as output:
            cli.print_status(self.path, runtime)
        self.assertIn('MQTT: MQTT_PAUSED', output.getvalue())
        self.assertIn('Last broker PUBACK (QoS1): ack-time', output.getvalue())
        for mutation in ({'MainPID': '124'}, {'ExecMainStartTimestampMonotonic': str(int((mono + 10) * 1e6))}):
            with self.subTest(mutation=mutation), patch('app.runtime_status.host_identity', return_value={}), patch.object(cli, 'service_info', return_value=dict(service, **mutation)), contextlib.redirect_stdout(io.StringIO()) as output:
                cli.print_status(self.path, runtime)
            self.assertIn('MQTT: UNKNOWN', output.getvalue())

    def test_empty_assignment_can_be_updated_and_invalid_config_repaired(self):
        self.path.write_text('[mqtt]\nhost =\npassword =\n')
        with patch.object(cli, 'service_info', return_value={'ActiveState': 'inactive'}), patch('sys.stdin', io.StringIO('new-secret\n')):
            self.assertTrue(cli.set_config(self.path, ['mqtt_host=new', 'mqtt_password=-']))
        self.assertEqual(load_config(self.path).mqtt.password, 'new-secret')
        self.assertEqual(load_config(self.path).mqtt.host, 'new')

    def test_restart_command_targets_existing_agent_only(self):
        with patch.object(cli.subprocess, 'run') as run:
            run.return_value.returncode = 0
            cli.restart_service()
        self.assertEqual(run.call_args.args[0], ['systemctl', 'restart', 'digitalhouses_plex_agent.service'])

    def test_nonroot_mutation_rejected_and_help_lists_all_keys(self):
        with patch.object(cli.os, 'geteuid', return_value=1000), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertNotEqual(cli.main(['restart']), 0)
            self.assertEqual(cli.main(['help']), 0)
        for key in cli.KEYS:
            self.assertIn(key, output.getvalue())

    def test_main_failure_nonzero_and_no_secret(self):
        with patch.object(cli.os, 'geteuid', return_value=0), patch.object(cli, 'DEFAULT_CONFIG', self.path), contextlib.redirect_stdout(io.StringIO()) as output:
            result = cli.main(['set', 'mqtt_password=do-not-print'])
        self.assertNotEqual(result, 0)
        self.assertIn('ERROR', output.getvalue())
        self.assertNotIn('do-not-print', output.getvalue())


if __name__ == '__main__':
    unittest.main()
