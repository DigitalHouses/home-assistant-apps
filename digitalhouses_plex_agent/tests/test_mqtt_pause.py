"""Deterministic main-loop regression tests; no broker, sleeps or real collectors."""
import importlib
from pathlib import Path
import sys
import tempfile
import threading
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def import_runtime():
    # Missing optional test-environment dependencies are replaced only during
    # module import. Every process/network boundary below is explicitly mocked.
    replacements = {}
    for name in ('psutil', 'paho.mqtt.client'):
        try:
            importlib.import_module(name)
        except ImportError:
            replacements[name] = ModuleType(name)
    if 'paho.mqtt.client' in replacements:
        replacements['paho'] = ModuleType('paho')
        replacements['paho.mqtt'] = ModuleType('paho.mqtt')
    with patch.dict(sys.modules, replacements):
        return importlib.import_module('app.app')


class PauseTests(unittest.TestCase):
    def exercise(self, *, initially_online, fail_first_collection=False, disconnect_during_flush=False, poll_interval=10):
        app = import_runtime()
        clock = [0.0]
        bridge = MagicMock()
        for name in ('connected', 'wake_requested', 'republish_requested', 'refresh_requested',
                     'restart_requested', 'install_update_requested', 'check_updates_requested'):
            setattr(bridge, name, threading.Event())
        if initially_online:
            bridge.connected.set()
            bridge.republish_requested.set()
        bridge.diagnostics.side_effect = lambda: {'state': 'CONNECTED' if bridge.connected.is_set() else 'MQTT_PAUSED'}
        waits = []
        collected = []
        handlers = {}
        publications = []
        def mono():
            clock[0] += 1
            if clock[0] > 1000:
                self.fail('loop spun without a blocking event wait')
            return clock[0]
        def wait(timeout=None):
            waits.append(timeout)
            # Make the uptime heartbeat overdue while disconnected.
            clock[0] += 120
            if len(waits) == 1 and initially_online:
                bridge.connected.clear()
            elif (initially_online and len(waits) == 2) or not initially_online:
                self.assertEqual(len(collected), 1 if initially_online and not disconnect_during_flush else 0)
                bridge.connected.set()
                bridge.republish_requested.set()
            else:
                handlers[app.signal.SIGTERM](15, None)
            return True
        bridge.wake_requested.wait = wait
        publication = MagicMock()
        events = MagicMock()
        if disconnect_during_flush:
            disconnected = [False]
            def flush(_):
                if not disconnected[0]:
                    disconnected[0] = True
                    bridge.connected.clear()
                return 0
            events.flush.side_effect = flush
        def publish(snapshot, api, **kw):
            publications.append(snapshot)
            if len(collected) >= (2 if initially_online and not disconnect_during_flush else 1):
                handlers[app.signal.SIGTERM](15, None)
            return True
        publication.publish_snapshot.side_effect = publish
        api = MagicMock(status='disabled')
        api.poll.return_value = None
        api.collect.return_value = SimpleNamespace(failure_transition=False, recovered=False, libraries_changed=False)
        api.payload.return_value = {'plex_api_status':'disabled'}
        gpu_reader = MagicMock()
        card = MagicMock(state='idle', operation=None)
        updates = MagicMock()
        updates.poll.return_value = None
        cfg = SimpleNamespace(
            general=SimpleNamespace(instance_id='plex',poll_interval_seconds=poll_interval,cpu_window_seconds=3600),
            telemetry=SimpleNamespace(high_load_threshold=80),plex_api=SimpleNamespace(enabled=False),
            mqtt=SimpleNamespace(host='mqtt',port=1883))
        def raw():
            self.assertTrue(bridge.connected.is_set(), 'foreground collector ran offline')
            collected.append(clock[0])
            if fail_first_collection and len(collected) == 1:
                raise app.CollectorError('test collector failure')
            return []
        with tempfile.TemporaryDirectory() as directory, patch.multiple(
            app, verify_proc_visibility=MagicMock(), _telemetry_runner=MagicMock(return_value=None),
            MqttBridge=MagicMock(return_value=bridge), PlexApiRuntime=MagicMock(return_value=api),
            AgentCard=MagicMock(return_value=card), UpdateManager=MagicMock(return_value=updates),
            GpuEventTracker=MagicMock(return_value=events), GpuStateReader=MagicMock(return_value=gpu_reader), gpu_driver_info=MagicMock(return_value={}),
            gpu_operational_problem=MagicMock(return_value=(None,None)),
            PlexPublicationRuntime=MagicMock(return_value=publication),
            collect_raw_processes=raw, build_topics=MagicMock(), build_discovery_payload=MagicMock(),
        ), patch.object(app.time,'monotonic',side_effect=mono), patch.object(
            app.signal,'signal',side_effect=lambda sig, fn: handlers.update({sig:fn})
        ), patch.object(app.psutil,'boot_time',return_value=0,create=True), patch.object(
            app.psutil,'cpu_count',return_value=1,create=True
        ), patch('app.runtime_status.host_identity',return_value={'hostname':'vm','ip':'10.0.0.1'}), patch.object(
            app,'CONTROL_STATE_DIR',Path(directory)
        ), patch('logging.Logger.exception'):
            self.assertEqual(app.run(cfg),0)
        self.assertGreaterEqual(len(waits), 2 if initially_online else 1)
        self.assertEqual(len(collected), 2 if initially_online and not disconnect_during_flush else 1)
        self.assertEqual(api.collect.call_count,len(collected))
        self.assertEqual(gpu_reader.collect.call_count, len(collected))
        publication.republish_cached.assert_not_called()
        self.assertTrue(publication.publish_snapshot.call_args.kwargs['force'])
        self.assertIn(30.0, waits)
        self.assertLessEqual(max(waits), 30.0)
        return bridge

    def test_loss_of_mqtt_past_heartbeat_blocks_then_collects_fresh(self):
        self.exercise(initially_online=True)

    def test_failed_first_collector_does_not_spin_before_next_poll(self):
        self.exercise(initially_online=True, fail_first_collection=True)

    def test_disconnect_during_outbox_ack_wait_skips_process_collection(self):
        self.exercise(initially_online=True, disconnect_during_flush=True)

    def test_long_poll_interval_still_wakes_for_local_status_cadence(self):
        self.exercise(initially_online=True, poll_interval=300)

    def test_initial_broker_offline_waits_before_any_collection(self):
        self.exercise(initially_online=False)


if __name__ == '__main__':
    unittest.main()
