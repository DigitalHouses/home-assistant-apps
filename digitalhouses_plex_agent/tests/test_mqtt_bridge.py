import sys
import types
from pathlib import Path
import unittest
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Make app.mqtt_bridge importable without the external paho dependency.
client_module = types.ModuleType("paho.mqtt.client")
client_module.MQTT_ERR_SUCCESS = 0
client_module.MQTT_ERR_NO_CONN = 4
client_module.CallbackAPIVersion = types.SimpleNamespace(VERSION2=2)
client_module.Client = object
client_module.ConnectFlags = object
client_module.ReasonCode = object
client_module.Properties = object
client_module.DisconnectFlags = object
client_module.MQTTMessage = object
mqtt_module = types.ModuleType("paho.mqtt")
mqtt_module.client = client_module
paho_module = types.ModuleType("paho")
paho_module.mqtt = mqtt_module
sys.modules.setdefault("paho", paho_module)
sys.modules.setdefault("paho.mqtt", mqtt_module)
sys.modules.setdefault("paho.mqtt.client", client_module)

from app.mqtt_bridge import MqttBridge


class PublishInfo:
    rc = 0
    mid = 1

    def wait_for_publish(self, timeout):
        pass

    def is_published(self):
        return True


class FakeClient:
    def __init__(self):
        self.calls = []

    def publish(self, topic, payload, qos, retain):
        self.calls.append((topic, payload, qos, retain))
        return PublishInfo()



def initialize(bridge, connected=True):
    bridge.connected = threading.Event()
    if connected:
        bridge.connected.set()
    bridge.wake_requested = threading.Event()
    bridge._lock = threading.RLock()
    bridge._event_lock = threading.Lock()
    bridge._diagnostics = {"state": "DISCONNECTED", "last_connected": None,
                           "last_error": None, "last_publish": None,
                           "last_ack": None, "publication_state": "idle",
                           "reconnect_seconds": 60}
    bridge._pending_events = {}
    bridge.log = Mock()


class MqttReliabilityTests(unittest.TestCase):
    def bridge(self):
        b = MqttBridge.__new__(MqttBridge)
        initialize(b)
        b.client = FakeClient()
        b.topics = SimpleNamespace(state="plex/state", discovery="ha/discovery",
            diagnostic_event="plex/events", collector_availability="plex/collector",
            plex_api_availability="plex/api", agent_card_state="plex/card", update_state="plex/update")
        b.discovery_payload = {}
        b.sync_payload = None
        b._collector_available = None
        b._plex_api_available = None
        return b

    def test_discovery_waits_for_ack_and_reuses_single_receipt(self):
        b = self.bridge()
        info = Mock(rc=4)
        info.is_published.return_value = False
        b.client.publish = Mock(return_value=info)
        self.assertFalse(b.publish_discovery())
        self.assertFalse(b.publish_discovery())
        b.set_discovery_payload({'components': {'new': {}}})
        self.assertFalse(b.publish_discovery())
        self.assertEqual(b.client.publish.call_count, 1)
        info.is_published.return_value = True
        self.assertTrue(b.publish_discovery())
        self.assertEqual(b.client.publish.call_count, 2)
        self.assertEqual(b.client.publish.call_args.kwargs['qos'], 1)
        self.assertTrue(b.client.publish.call_args.kwargs['retain'])
        info.wait_for_publish.assert_called_with(timeout=2.0)

    def test_discovery_receipt_survives_disconnect_without_duplicate(self):
        b = self.bridge()
        info = Mock(rc=4)
        info.is_published.return_value = False
        b.client.publish = Mock(return_value=info)
        self.assertFalse(b.publish_discovery())
        b.connected.clear()
        self.assertFalse(b.publish_discovery())
        b.connected.set()
        info.is_published.return_value = True
        self.assertTrue(b.publish_discovery())
        self.assertEqual(b.client.publish.call_count, 1)

    def test_discovery_calls_paho_and_wait_without_locks(self):
        b = self.bridge()
        info = Mock(rc=0)
        ack = [False]
        def check_locks(*args, **kwargs):
            self.assertFalse(b._lock._is_owned())
            self.assertFalse(b._event_lock.locked())
        def publish(*args, **kwargs):
            check_locks()
            return info
        def wait(**kwargs):
            check_locks()
            ack[0] = True
        info.is_published.side_effect = lambda: ack[0]
        info.wait_for_publish.side_effect = wait
        b.client.publish = publish
        self.assertTrue(b.publish_discovery())

    def test_owned_cleanup_requires_ack_and_reuses_receipt(self):
        b = self.bridge()
        b.topics.base = 'plex'
        info = Mock(rc=0)
        info.is_published.return_value = False
        b.client.publish = Mock(return_value=info)
        self.assertFalse(b.clear_discovery_state('plex/state/obsolete'))
        self.assertFalse(b.clear_discovery_state('plex/state/obsolete'))
        self.assertEqual(b.client.publish.call_count, 1)
        info.is_published.return_value = True
        self.assertTrue(b.clear_discovery_state('plex/state/obsolete'))
        self.assertEqual(b.client.publish.call_count, 1)
        self.assertEqual(b.client.publish.call_args.kwargs['qos'], 1)
        self.assertTrue(b.client.publish.call_args.kwargs['retain'])
        self.assertEqual(b.client.publish.call_args.kwargs['payload'], '')

    def test_cleanup_rejects_foreign_discovery_and_availability_topics(self):
        b = self.bridge()
        b.topics.base = 'plex'
        for topic in ('plex-other/state/a', 'other/state/a', 'plex/availability',
                      'ha/discovery', 'plex/state/#', 'plex/events/diagnostic'):
            self.assertFalse(b.clear_discovery_state(topic))
        self.assertEqual(b.client.calls, [])
        self.assertTrue(b.clear_discovery_state('plex/state/removed'))
        self.assertEqual(b.client.calls, [('plex/state/removed', '', 1, True)])

    def test_discovery_queue_full_retries_without_caching_rejected_receipt(self):
        b = self.bridge()
        b.client.publish = Mock(side_effect=[Mock(rc=15), PublishInfo()])
        self.assertFalse(b.publish_discovery())
        self.assertTrue(b.publish_discovery())
        self.assertEqual(b.client.publish.call_count, 2)

    def test_all_publications_skip_disconnected_client(self):
        b = self.bridge()
        b.connected.clear()
        for publish in (lambda: b.publish_state({}), lambda: b.publish_state_group("cpu", {}),
                        b.publish_discovery, b.clear_legacy_state,
                        lambda: b.set_collector_available(True), lambda: b.set_plex_api_available(True)):
            self.assertFalse(publish())
        self.assertEqual(b.client.calls, [])

    def test_qos1_queue_acceptance_is_not_ack_and_retry_reuses_pending(self):
        b = self.bridge()
        info = Mock(rc=0)
        info.is_published.return_value = False
        b.client.publish = Mock(return_value=info)
        event = {"event_id": "persistent-id"}
        self.assertFalse(b.publish_diagnostic_event(event))
        self.assertFalse(b.publish_diagnostic_event(event))
        self.assertEqual(b.client.publish.call_count, 1)
        info.is_published.return_value = True
        self.assertTrue(b.publish_diagnostic_event(event))
        self.assertEqual(b.client.publish.call_count, 1)
        self.assertIsNotNone(b.diagnostics()["last_ack"])
        info.wait_for_publish.assert_called_with(timeout=2.0)

    def test_publish_does_not_hold_callback_diagnostics_lock(self):
        b = self.bridge()
        callback_threads = []
        def publish_with_callback(*args, **kwargs):
            completed = threading.Event()
            def callback():
                b._on_publish(b.client, None, 1, SimpleNamespace(is_failure=False), None)
                completed.set()
            thread = threading.Thread(target=callback)
            callback_threads.append(thread)
            thread.start()
            self.assertTrue(completed.wait(0.5), "publication blocks Paho callback")
            return PublishInfo()
        b.client.publish = publish_with_callback
        try:
            self.assertTrue(b.publish_state({}))
            self.assertTrue(b.publish_diagnostic_event({"event_id": "one"}))
            self.assertTrue(b.set_collector_available(True))
            self.assertTrue(b.set_plex_api_available(True))
        finally:
            for thread in callback_threads:
                thread.join(1)

    def test_acknowledged_orphan_receipts_do_not_permanently_fill_queue(self):
        b = self.bridge()
        b._pending_events = {str(i): PublishInfo() for i in range(32)}
        self.assertTrue(b.publish_diagnostic_event({"event_id": "newest"}))
        self.assertLess(len(b._pending_events), 32)
        self.assertEqual(len(b.client.calls), 1)

    def test_cleanup_does_not_republish_acknowledged_current_event(self):
        b = self.bridge()
        b._pending_events = {"current": PublishInfo(), "orphan": PublishInfo()}
        self.assertTrue(b.publish_diagnostic_event({"event_id": "current"}))
        self.assertEqual(b.client.calls, [])

    def test_no_conn_qos1_receipt_retained_until_reconnect_puback(self):
        from tempfile import TemporaryDirectory
        from app.gpu_events import GpuEventTracker
        b = self.bridge()
        info = PublishInfo()
        info.rc = 4
        info.mid = 77
        info.acknowledged = False
        info.is_published = lambda: info.acknowledged
        b.client.publish = Mock(return_value=info)
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.json"
            tracker = GpuEventTracker(path)
            tracker.outbox = [{"event_id": "survives-race"}]
            tracker._save()
            self.assertEqual(tracker.flush(b.publish_diagnostic_event), 0)
            self.assertEqual(len(GpuEventTracker(path).outbox), 1)
            self.assertIsNone(b.diagnostics()["last_ack"])
            self.assertEqual(tracker.flush(b.publish_diagnostic_event), 0)
            self.assertEqual(b.client.publish.call_count, 1)
            self.assertEqual(info.rc, 0)  # normalized local pending, never delivery
            b._on_publish(b.client, None, 77, SimpleNamespace(is_failure=False), None)
            # QoS0 can reuse the same MID after wrap; callback alone is no ACK.
            self.assertEqual(tracker.flush(b.publish_diagnostic_event), 0)
            self.assertIsNone(b.diagnostics()["last_ack"])
            info.acknowledged = True  # Paho receipt marked published by QoS1 PUBACK
            self.assertEqual(tracker.flush(b.publish_diagnostic_event), 1)
            self.assertEqual(b.client.publish.call_count, 1)
            self.assertEqual(GpuEventTracker(path).outbox, [])
            self.assertIsNotNone(b.diagnostics()["last_ack"])

    def test_puback_arriving_before_publish_returns_is_not_lost(self):
        b = self.bridge()
        info = PublishInfo()
        info.rc = 4
        info.mid = 77
        info.acknowledged = False
        info.is_published = lambda: info.acknowledged
        def publish(*args, **kwargs):
            b._on_publish(b.client, None, 77, SimpleNamespace(is_failure=False), None)
            info.acknowledged = True
            return info
        b.client.publish = publish
        self.assertTrue(b.publish_diagnostic_event({"event_id": "fast-ack"}))

    def test_qos0_mid_reuse_callback_cannot_acknowledge_qos1_receipt(self):
        b = self.bridge()
        info = PublishInfo()
        info.is_published = lambda: False
        b.client.publish = Mock(return_value=info)
        event = {"event_id": "qos1-still-pending"}
        self.assertFalse(b.publish_diagnostic_event(event))
        b._on_publish(b.client, None, info.mid, SimpleNamespace(is_failure=False), None)
        self.assertFalse(b.publish_diagnostic_event(event))
        self.assertIsNone(b.diagnostics()["last_ack"])
        self.assertEqual(b.client.publish.call_count, 1)

    def test_qos1_queue_full_error_is_not_kept_for_replay(self):
        b = self.bridge()
        b.client.publish = Mock(return_value=Mock(rc=15, mid=77))
        self.assertFalse(b.publish_diagnostic_event({"event_id": "queue-full"}))
        self.assertEqual(b._pending_events, {})

    def test_qos0_local_acceptance_does_not_claim_broker_ack(self):
        b = self.bridge()
        self.assertTrue(b.publish_state({"fresh": True}))
        self.assertIsNone(b.diagnostics()["last_ack"])
        self.assertEqual(b.diagnostics()["publication_state"], "qos0_local_accept")

    def test_paho2_reconnect_restores_subscriptions_and_signals_foreground(self):
        b = self.bridge()
        b.connected.clear()
        b.republish_requested = threading.Event()
        b.topics.ha_status = "ha/status"
        b.topics.refresh = "plex/refresh"
        b.topics.update_check = "plex/check"
        b.topics.update_install = "plex/install"
        b.topics.restart_agent = "plex/restart"
        b.topics.app_availability = "plex/availability"
        b.client.subscribe = Mock()
        for _ in range(2):
            b._on_connect(b.client, None, SimpleNamespace(session_present=False),
                          SimpleNamespace(is_failure=False), None)
            self.assertTrue(b.connected.is_set())
            self.assertTrue(b.republish_requested.is_set())
            self.assertTrue(b.wake_requested.is_set())
            self.assertEqual(b.diagnostics()["state"], "CONNECTED")
            self.assertIsNotNone(b.diagnostics()["last_connected"])
            b._on_disconnect(b.client, None, SimpleNamespace(), "network lost", None)
            self.assertFalse(b.connected.is_set())
        self.assertEqual(b.client.subscribe.call_count, 10)

    def test_rejected_paho2_connect_does_not_publish_or_claim_connection(self):
        b = self.bridge()
        b._on_connect(b.client, None, SimpleNamespace(),
                      SimpleNamespace(is_failure=True), None)
        self.assertFalse(b.connected.is_set())
        self.assertEqual(b.client.calls, [])
        self.assertTrue(b.wake_requested.is_set())

    def test_paho2_qos0_completion_tracks_sent_time_without_broker_ack(self):
        b = self.bridge()
        b._on_publish(b.client, None, 1, SimpleNamespace(is_failure=False), None)
        self.assertIsNotNone(b.diagnostics()["last_publish"])
        self.assertIsNone(b.diagnostics()["last_ack"])

    def test_transport_configuration(self):
        from app.config import load_config
        from app.discovery import build_topics
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config"
            config_path.write_text("[mqtt]\nhost = broker\n")
            config = load_config(config_path)
            client = Mock()
            with patch("app.mqtt_bridge.mqtt.Client", return_value=client):
                b = MqttBridge(config, build_topics(config), {})
            client.reconnect_delay_set.assert_called_once_with(60, 60)
            client.max_queued_messages_set.assert_called_once_with(32)
            self.assertEqual(client.connect_timeout, 5.0)
            self.assertEqual(client.on_connect_fail, b._on_connect_fail)

    def test_failed_connect_transition_wakes_and_does_not_repeat_logs(self):
        b = self.bridge()
        b.connected.clear()
        b._on_connect_fail(b.client, None)
        self.assertTrue(b.wake_requested.is_set())
        self.assertEqual(b.diagnostics()["state"], "MQTT_PAUSED")
        b._on_connect_fail(b.client, None)
        self.assertEqual(b.log.warning.call_count, 1)


class Topics:
    plex_api_availability = "base/plex_api_availability"


class MqttBridgePlexApiTests(unittest.TestCase):
    def test_plex_api_availability_is_retained_and_deduplicated(self):
        bridge = MqttBridge.__new__(MqttBridge)
        bridge.topics = Topics()
        bridge.client = FakeClient()
        bridge._plex_api_available = None
        initialize(bridge)

        self.assertTrue(bridge.set_plex_api_available(True))
        self.assertTrue(bridge.set_plex_api_available(True))
        self.assertEqual(
            bridge.client.calls,
            [("base/plex_api_availability", "online", 0, True)],
        )
        self.assertTrue(bridge.set_plex_api_available(False))
        self.assertEqual(bridge.client.calls[-1][1], "offline")

    def test_discovery_payload_can_be_replaced_after_library_scan(self):
        bridge = MqttBridge.__new__(MqttBridge)
        initialize(bridge)
        bridge.discovery_payload = {"components": {}}
        new_payload = {"components": {"library_1": {}}}
        bridge.set_discovery_payload(new_payload)
        self.assertIs(bridge.discovery_payload, new_payload)



class MqttBridgeControlTests(unittest.TestCase):
    def _bridge(self):
        b = MqttBridge.__new__(MqttBridge)
        b.topics = SimpleNamespace(
            ha_status="homeassistant/status",
            refresh="plex/refresh",
            update_check="plex/update/check",
            update_install="plex/update/install",
            restart_agent="plex/restart",
        )
        b.refresh_requested = threading.Event()
        b.check_updates_requested = threading.Event()
        b.install_update_requested = threading.Event()
        b.restart_requested = threading.Event()
        b.wake_requested = threading.Event()
        b.log = Mock()
        return b

    def test_retained_commands_are_rejected(self):
        bridge = self._bridge()
        for topic, event in (
            (bridge.topics.refresh, bridge.refresh_requested),
            (bridge.topics.update_check, bridge.check_updates_requested),
            (bridge.topics.update_install, bridge.install_update_requested),
            (bridge.topics.restart_agent, bridge.restart_requested),
        ):
            bridge._on_message(None, None, SimpleNamespace(
                topic=topic, payload=b"PRESS", retain=True,
            ))
            self.assertFalse(event.is_set())

    def test_exact_press_dispatches_once(self):
        bridge = self._bridge()
        for topic, event in (
            (bridge.topics.refresh, bridge.refresh_requested),
            (bridge.topics.update_check, bridge.check_updates_requested),
            (bridge.topics.update_install, bridge.install_update_requested),
            (bridge.topics.restart_agent, bridge.restart_requested),
        ):
            bridge._on_message(None, None, SimpleNamespace(
                topic=topic, payload=b"NOT-PRESS", retain=False,
            ))
            self.assertFalse(event.is_set())
            bridge._on_message(None, None, SimpleNamespace(
                topic=topic, payload=b"PRESS", retain=False,
            ))
            self.assertTrue(event.is_set())
            event.clear()



class GpuDiagnosticMqttEventTests(unittest.TestCase):
    def test_nonretained_qos1_event_published_only_when_connected(self):
        bridge = MqttBridge.__new__(MqttBridge)
        bridge.client = FakeClient()
        bridge.topics = SimpleNamespace(diagnostic_event="plex/events/diagnostic")
        initialize(bridge, connected=False)
        payload = {
            "schema_version": 2,
            "event_type": "gpu_unavailable",
            "gpu_status": "error",
            "driver_name": "i915",
        }
        self.assertFalse(bridge.publish_diagnostic_event(payload))
        self.assertEqual(bridge.client.calls, [])
        bridge.connected.set()
        self.assertTrue(bridge.publish_diagnostic_event(payload))
        topic, raw, qos, retained = bridge.client.calls[-1]
        self.assertEqual(topic, "plex/events/diagnostic")
        self.assertEqual(qos, 1)
        self.assertFalse(retained)
        self.assertEqual(__import__("json").loads(raw), payload)

    def test_mqtt_error_does_not_acknowledge_diagnostic_event(self):
        bridge = MqttBridge.__new__(MqttBridge)
        bridge.topics = SimpleNamespace(diagnostic_event="plex/events/diagnostic")
        initialize(bridge, connected=False)
        bridge.connected.set()
        client = FakeClient()
        info = Mock(rc=4, mid=1)
        info.wait_for_publish.side_effect = RuntimeError("not connected")
        info.is_published.return_value = False
        client.publish = lambda *args, **kwargs: info
        bridge.client = client
        self.assertFalse(bridge.publish_diagnostic_event({
            "event_type": "gpu_unavailable"
        }))


if __name__ == "__main__":
    unittest.main()
