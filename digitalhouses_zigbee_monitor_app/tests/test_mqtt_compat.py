"""Regression coverage: Alpine paho-mqtt 1.x and modern 2.x APIs."""
import unittest
from types import SimpleNamespace
from zigbee_monitor.mqtt_compat import create_mqtt_client, connection_failed

class Legacy:
    def __init__(self, *, client_id):
        self.client_id = client_id

class Modern:
    def __init__(self, version, *, client_id):
        self.version = version
        self.client_id = client_id

class MqttCompatibilityTests(unittest.TestCase):
    def test_paho_v1_constructor(self):
        client = create_mqtt_client(SimpleNamespace(Client=Legacy), client_id="dh-zigbee")
        self.assertEqual(client.client_id, "dh-zigbee")

    def test_paho_v2_constructor(self):
        marker = object()
        module = SimpleNamespace(Client=Modern, CallbackAPIVersion=SimpleNamespace(VERSION2=marker))
        client = create_mqtt_client(module, client_id="dh-zigbee")
        self.assertIs(client.version, marker)

    def test_reason_codes(self):
        self.assertFalse(connection_failed(0))
        self.assertTrue(connection_failed(5))
        self.assertFalse(connection_failed(SimpleNamespace(is_failure=False)))
        self.assertTrue(connection_failed(SimpleNamespace(is_failure=True)))

    def test_actual_installed_paho_client(self):
        import paho.mqtt.client as mqtt
        client = create_mqtt_client(mqtt, client_id="dh-zigbee-test")
        self.assertIsNotNone(client)

if __name__ == "__main__":
    unittest.main()
