"""Smoke-check the standalone passive MQTT recorder without a live broker."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "examples/tests/passive_group_observer.py"
spec = importlib.util.spec_from_file_location("aqara_passive_group_observer", SCRIPT)
observer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observer)


class MQTTClient:
    def __init__(self, **kwargs):
        self.subscribed = []
        self.on_connect = None
        self.on_disconnect = None
        self.on_message = None

    def reconnect_delay_set(self, **kwargs):
        pass

    def username_pw_set(self, *args):
        pass

    def subscribe(self, topic, qos=0):
        self.subscribed.append(topic)

    def connect(self, host, port, keepalive):
        pass

    def loop_start(self):
        self.on_connect(self, None, None, 0)

    def disconnect(self):
        pass

    def loop_stop(self):
        pass


class MQTTModule:
    Client = MQTTClient


class PassiveGroupObserverTest(unittest.TestCase):
    def test_only_selected_topics_no_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "log.jsonl"
            app = observer.Observer(
                MQTTModule, {"host": "broker", "port": 1883},
                "zigbee2mqtt_1", "zg_bedroom_tube_lights",
                ["left", "right"], path, 0.000001,
            )
            self.assertEqual(app.run(), 0)
            self.assertEqual(len(app.client.subscribed), 10)
            self.assertNotIn("zigbee2mqtt_1/#", app.client.subscribed)
            self.assertFalse(hasattr(app.client, "publish"))
            self.assertIn("subscribe-only", path.read_text())

    def test_state_not_promoted_to_confirmation(self):
        state = observer.compact(
            b'{"state":"OFF","brightness":254,"linkquality":109,"voltage":230}',
            "member", "group",
        )
        self.assertEqual(state, {"state": "OFF", "brightness": 254, "linkquality": 109})

    def test_group_only_reports_selected_members(self):
        payload = (b'[{"friendly_name":"another","members":[]},'
                   b'{"friendly_name":"target","id":112,'
                   b'"members":[{"ieee_address":"0xabcdef","endpoint":1}]}]')
        result = observer.compact(payload, "membership", "target")
        self.assertEqual(result["id"], 112)
        self.assertEqual(result["members"], [{"ieee":"0xabcdef", "endpoint":1}])


if __name__ == "__main__":
    unittest.main()
