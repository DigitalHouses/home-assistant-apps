"""Ensure no scan is triggered by startup or retained Zigbee2MQTT snapshots."""
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from aqara_switch.runtime import Application
from aqara_switch.mqtt_ui import SCAN_REQUEST


class MQTTResult:
    rc = 0


class FakeClient:
    def __init__(self, **kwargs):
        self.on_connect = None
        self.on_message = None
        self.on_disconnect = None
        self.subscriptions = []
        self.published = []

    def will_set(self,*args,**kwargs):
        pass
    def reconnect_delay_set(self,**kwargs):
        pass
    def subscribe(self,topic,qos):
        self.subscriptions.append(topic)
        return (0,1)
    def publish(self,topic,payload,qos,retain):
        self.published.append((topic,payload,retain))
        return MQTTResult()


class RuntimeManualTests(unittest.TestCase):
    def test_startup_never_scans_or_writes_options(self):
        options=Mock()
        options.read.return_value={"configuration_yaml":"rooms: []\n"}
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


if __name__=="__main__":
    unittest.main()
