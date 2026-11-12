import json
import tempfile
from pathlib import Path
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from app.config import load_config
from app.disk_temperature import DiskTemperatureReader
from app.restart_safety import guard_restart
from app.runtime_status import read_status, sample_live, RuntimeStatus
from app.ups_nut import parse_upsc_output
from test_ups_group_runtime import _runtime
from test_mqtt_bridge import _mqtt, _topics
from app.mqtt_bridge import MqttBridge
from app.runtime_settings import RuntimeSettings


class OfflineRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_ups_starts_and_polls_with_failed_cleanup_and_pending_events(self):
        clock = {'iso': '2026-11-12T00:00:00Z', 'mono': 0.0}
        reads = []
        def read(config):
            reads.append(config.name)
            return parse_upsc_output('ups.status: OB\nbattery.charge: 25\n')
        bridge, runtime = _runtime(self.root, read, clock)
        bridge.clear_legacy_ups_state = lambda: False
        bridge.publish_ups_state_group = lambda *args: False
        runtime._flush_machine_event_outbox = lambda: False
        runtime._flush_pending_problem_transitions = lambda: False
        runtime.startup()
        self.assertGreaterEqual(len(reads), 1)
        clock['mono'] = 10
        runtime.tick(10)
        self.assertGreaterEqual(len(reads), 2)
        self.assertTrue(runtime.last_snapshot.on_battery)
        count = len(reads)
        runtime.tick(10.1)
        self.assertEqual(count, len(reads))

    def test_ups_reconnect_publishes_latest_not_cached_online_snapshot(self):
        clock = {'iso': '2026-11-12T00:00:00Z', 'mono': 0.0}
        current = ['OL']
        bridge, runtime = _runtime(self.root, lambda config: parse_upsc_output('ups.status: ' + current[0]), clock)
        runtime.startup()
        bridge.groups.clear()
        current[0] = 'OB'
        runtime.republish_after_reconnect()
        self.assertTrue(runtime.last_snapshot.on_battery)
        self.assertIn('OB', json.dumps(bridge.groups))

    def test_main_boot_with_mqtt_down_starts_local_and_ups_runtime(self):
        from app import main
        from contextlib import ExitStack
        config_file = self.root / 'config'
        config_file.write_text('[mqtt]\nhost=broker\n')
        config = load_config(config_file)
        bridge = MagicMock()
        # All actual command queues empty; MQTT never connected.
        for name in ('ups_debug_updates',):
            getattr(bridge, name).empty.return_value = True
        for name in ('connected', 'restart_requested', 'check_updates_requested', 'install_update_requested', 'refresh_requested', 'reconnect_requested', 'ups_scan_requested'):
            getattr(bridge, name).is_set.return_value = False
        runtime = MagicMock()
        runtime.startup.return_value = False  # Publication failure is not local startup failure.
        runtime.settings = RuntimeSettings()
        runtime._subsystems = {}
        runtime.problem_engine = None
        ups = MagicMock()
        ups.startup.return_value = False
        ups.last_snapshot = None
        ups.local_problem_fields = None
        handlers = {}
        ticks = []
        def wait(timeout):
            ticks.append(timeout)
            if len(ticks) >= 3:
                handlers[main.signal.SIGTERM](main.signal.SIGTERM, None)
        bridge.wake_requested.wait.side_effect = wait
        with ExitStack() as stack:
            for name in ('_shutdown_tracker', 'UpsDebugRecorder', 'TelemetryRunner', '_telemetry_client', 'UpdateManager', 'AgentCard', 'MemoryDiagnostics', 'NfsFailureMonitor', 'FanCalibrationManager', 'collect_fans', 'ThreadPoolExecutor'):
                obj = stack.enter_context(patch.object(main, name))
                if name == 'AgentCard':
                    obj.return_value.state = 'idle'
                if name == 'UpdateManager':
                    obj.return_value._is_worker_busy.return_value = False
            stack.enter_context(patch.object(main, 'build_ups_scanner')).return_value.selected_name.return_value = 'ups'
            stack.enter_context(patch.object(main, 'build_runtime', return_value=(bridge, runtime)))
            stack.enter_context(patch.object(main, 'build_ups_runtime', return_value=ups))
            stack.enter_context(patch.object(main.signal, 'signal', side_effect=lambda sig, fn: handlers.update({sig: fn})))
            stack.enter_context(patch.object(main, 'RuntimeStatus'))
            stack.enter_context(patch.object(main, 'HostIdentity'))
            self.assertEqual(main.run(config, state_dir=self.root), 0)
        runtime.startup.assert_called_once()
        ups.startup.assert_called_once()
        self.assertGreaterEqual(ups.tick.call_count, 2)
        self.assertGreaterEqual(runtime.tick.call_count, 2)
        self.assertTrue(all(value == 1.0 for value in ticks))

    def test_shutdown_policy_still_commits_with_mqtt_publications_failing(self):
        from test_ups_trigger_runtime_v2 import _runtime as safety_runtime, _snapshot
        committed = []
        runtime, bridge, history = safety_runtime(
            self.root, [_snapshot('OB', 19, 9999)], executor=committed.append,
        )
        bridge.publish_ups_state_group = lambda *args: False
        bridge.publish_ups_availability = lambda *args: False
        runtime._flush_machine_event_outbox = lambda: False
        runtime._flush_pending_problem_transitions = lambda: False
        with self.assertLogs('app.ups_runtime', level='WARNING'):
            runtime.startup()
        self.assertEqual(committed, ['charge_guard'])
        evidence = json.loads((self.root / 'ups_shutdown_commit.json').read_text())
        self.assertTrue(evidence['committed'])
        self.assertEqual(len(history.software_commits), 1)

    def test_pve_collectors_continue_with_pending_publication(self):
        from app.app import CollectorSample
        from app.publish_policy import PublishPolicy
        from app.runtime_problems import ProblemAwareRuntime
        from app.scheduler import Scheduler
        from test_runtime_dynamic import GroupBridge, Store
        calls = []
        settings = RuntimeSettings()
        scheduler = Scheduler()
        scheduler.add('cpu', interval_seconds=10, now=0)
        runtime = ProblemAwareRuntime(
            collectors={'cpu': lambda: (calls.append(1) or CollectorSample(data={'temperature_c': 50}, metrics={}))},
            bridge=GroupBridge(), settings=settings, publish_policy=PublishPolicy(settings),
            state_store=Store(), scheduler=scheduler, now_iso=lambda: '2026-11-12T00:00:00Z',
            discovery_builder=lambda inv: {},
        )
        runtime._flush_pending_transitions = lambda: False
        runtime.startup()
        runtime.tick(10)
        self.assertGreaterEqual(len(calls), 2)

    def test_restart_gate_selected_name_and_battery_unknown_fsd_commit(self):
        conf = self.root / 'config'
        conf.write_text('[mqtt]\nhost=broker\n[ups]\nname=wrong\n')
        config = load_config(conf)
        (self.root / 'ups_selection.json').write_text('{"selected_name":"chosen"}')
        for status in ('', 'OB', 'OL LB', 'OL FSD', 'OL DISCHRG'):
            with self.subTest(status=status), patch('app.restart_safety.read_ups', return_value=parse_upsc_output('ups.status: ' + status)):
                with self.assertRaises(RuntimeError):
                    guard_restart(config, state_dir=self.root)
        with patch('app.restart_safety.read_ups', return_value=parse_upsc_output('ups.status: OL')) as reader:
            guard_restart(config, state_dir=self.root)
            self.assertEqual(reader.call_args.args[0].name, 'chosen')
        (self.root / 'shutdown_history.json').write_text('{"current_boot":{"fsd_at":"now"}}')
        with self.assertRaises(RuntimeError):
            guard_restart(config, state_dir=self.root)

    def test_nvme_namespace_uses_nvme_controller(self):
        sensor = self.root / 'class/nvme/nvme0/device/hwmon/hwmon1/temp1_input'
        sensor.parent.mkdir(parents=True)
        sensor.write_text('45000')
        self.assertEqual(DiskTemperatureReader(sys_root=self.root)._sysfs_temperature('/dev/nvme0n1'), 45)

    def test_status_rejects_reused_pid_old_age_and_stopped_service(self):
        from datetime import datetime, timezone
        path = self.root / 'status'
        stamp = datetime.now(timezone.utc).isoformat()
        service = {'ActiveState': 'active', 'MainPID': '42', 'ExecMainStartTimestampMonotonic': str(int((time.monotonic() - 5) * 1e6))}
        path.write_text(json.dumps({'pid': 42, 'started_at': stamp, 'updated_at': stamp}))
        self.assertTrue(read_status(path, service)[1])
        service['ActiveState'] = 'inactive'
        self.assertFalse(read_status(path, service)[1])
        service['ActiveState'] = 'active'
        path.write_text(json.dumps({'pid': 42, 'started_at': '2000-01-01T00:00:00Z', 'updated_at': stamp}))
        self.assertFalse(read_status(path, service)[1])
        self.assertFalse(sample_live('cpu', {'available': True, 'last_success': '2000-01-01T00:00:00Z'}))

    def test_mqtt_retry_bounds_and_no_offline_queue_actual_puback_only(self):
        client = MagicMock()
        bridge = MqttBridge(_mqtt(), _topics(), RuntimeSettings(), {}, client=client)
        client.reconnect_delay_set.assert_called_once_with(60, 60)
        self.assertEqual(client.connect_timeout, 5)
        client.max_queued_messages_set.assert_called_once_with(64)
        client.max_inflight_messages_set.assert_called_once_with(20)
        self.assertFalse(bridge.publish_state({'x': 1}))
        client.publish.assert_not_called()
        bridge.connected.set()
        info = SimpleNamespace(rc=0, mid=7, wait_for_publish=lambda **kwargs: None, is_published=lambda: False)
        client.publish.return_value = info
        self.assertFalse(bridge.publish_state({'x': 1}))
        self.assertIsNone(bridge.diagnostics()['last_ack'])
        # Callback for an unrelated / QoS0 MID must not count as a QoS1 ACK.
        bridge._on_publish(client, None, 99, None, None)
        self.assertIsNone(bridge.diagnostics()['last_ack'])
        bridge._on_publish(client, None, 7, None, None)
        self.assertIsNotNone(bridge.diagnostics()['last_ack'])

    def test_rejected_puback_is_not_success_even_if_paho_marks_completion(self):
        client = MagicMock()
        bridge = MqttBridge(_mqtt(), _topics(), RuntimeSettings(), {}, client=client)
        bridge.connected.set()
        def rejected(**kwargs):
            bridge._on_publish(client, None, 7, SimpleNamespace(is_failure=True), None)
        client.publish.return_value = SimpleNamespace(rc=0, mid=7, wait_for_publish=rejected, is_published=lambda: True)
        self.assertFalse(bridge.publish_state({'x': 1}))
        self.assertIsNone(bridge.diagnostics()['last_ack'])


if __name__ == '__main__':
    unittest.main()
