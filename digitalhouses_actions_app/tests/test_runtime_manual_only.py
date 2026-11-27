"""Ensure no scan is triggered by startup or retained Zigbee2MQTT snapshots."""
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from actions.runtime import Application
from actions.mqtt_ui import SCAN_REQUEST, SYNC_TOPIC


class MQTTResult:
    rc = 0


class FakeClient:
    def __init__(self, **kwargs):
        self.on_connect = None
        self.on_message = None
        self.on_disconnect = None
        self.subscriptions = []
        self.published = []
        self.published_qos = []

    def will_set(self,*args,**kwargs):
        pass
    def reconnect_delay_set(self,**kwargs):
        pass
    def subscribe(self,topic,qos):
        self.subscriptions.append(topic)
        return (0,1)
    def publish(self,topic,payload,qos,retain):
        self.published.append((topic,payload,retain))
        self.published_qos.append((topic,payload,qos,retain))
        return MQTTResult()


class RuntimeManualTests(unittest.TestCase):
    def test_startup_never_scans_or_writes_options(self):
        options=Mock()
        options.read.return_value={"switches":"[]"}
        registry=Mock()
        with tempfile.TemporaryDirectory() as td:
            app=Application(types.SimpleNamespace(Client=FakeClient),options=options,
                            registry=registry,last_scan_path=Path(td)/"last.json",
                            version="0.1.1")
            app._on_connect(None,None,None,0)
            self.assertEqual(options.write.call_count,0)
            self.assertEqual(registry.fetch.call_count,0)
            self.assertIn(SCAN_REQUEST,app.client.subscriptions)
            with patch.object(app,"request_scan") as scan:
                msg=types.SimpleNamespace(topic=SCAN_REQUEST,payload=b"SCAN",retain=True)
                app._on_message(None,None,msg)
                self.assertEqual(scan.call_count,0)
                msg.retain=False
                app._on_message(None,None,msg)
                self.assertEqual(scan.call_count,1)

    def test_dh_sync_retained_qos1_on_connect_and_reconnect(self):
        options = Mock()
        options.read.return_value = {"switches": "[]"}
        with tempfile.TemporaryDirectory() as td:
            app = Application(
                types.SimpleNamespace(Client=FakeClient), options=options,
                registry=Mock(), last_scan_path=Path(td)/"last.json",
                version="0.1.99",
            )
            app._on_connect(None, None, None, 5)
            self.assertFalse(app.client.published_qos)
            app._on_connect(None, None, None, 0)
            app._on_disconnect(None, None, 1)
            app._on_connect(None, None, None, 0)
            records = [entry for entry in app.client.published_qos
                       if entry[0] == SYNC_TOPIC]
            self.assertEqual(len(records), 2)
            expected = {
                "schema": 1,
                "product_id": "digitalhouses_actions_app",
                "type": "app",
                "version": "0.1.99",
                "repository": "https://github.com/DigitalHouses/home-assistant-apps",
                "product_path": "digitalhouses_actions_app",
            }
            for topic, payload, qos, retain in records:
                self.assertEqual(topic, "DigitalHouses/Global/digitalhouses_actions_app/sync")
                self.assertEqual(qos, 1)
                self.assertTrue(retain)
                self.assertEqual(json.loads(payload), expected)
            self.assertFalse(any(topic == SYNC_TOPIC and payload == ""
                                 for topic, payload, _, _ in app.client.published_qos))


if __name__=="__main__":
    unittest.main()
