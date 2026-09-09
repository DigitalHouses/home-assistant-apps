import sys
import types
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Make app.mqtt_bridge importable without the external paho dependency.
client_module = types.ModuleType("paho.mqtt.client")
client_module.MQTT_ERR_SUCCESS = 0
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


class FakeClient:
    def __init__(self):
        self.calls = []

    def publish(self, topic, payload, qos, retain):
        self.calls.append((topic, payload, qos, retain))
        return PublishInfo()


class Topics:
    plex_api_availability = "base/plex_api_availability"


class MqttBridgePlexApiTests(unittest.TestCase):
    def test_plex_api_availability_is_retained_and_deduplicated(self):
        bridge = MqttBridge.__new__(MqttBridge)
        bridge.topics = Topics()
        bridge.client = FakeClient()
        bridge._plex_api_available = None

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
        bridge.discovery_payload = {"components": {}}
        new_payload = {"components": {"library_1": {}}}
        bridge.set_discovery_payload(new_payload)
        self.assertIs(bridge.discovery_payload, new_payload)


if __name__ == "__main__":
    unittest.main()
