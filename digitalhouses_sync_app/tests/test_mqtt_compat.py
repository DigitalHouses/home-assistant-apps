"""Regression: HAOS apk may ship Paho 1.x although CI pip has Paho 2.x."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest

import app


class MqttCompatTests(unittest.TestCase):
    def test_paho_1_no_callback_api_version(self):
        constructor = Mock(return_value=object())
        with patch.object(app, "mqtt", SimpleNamespace(Client=constructor)):
            self.assertIsNotNone(app.create_mqtt_client())
        constructor.assert_called_once_with(client_id="digitalhouses-sync-app")

    def test_paho_2_uses_explicit_callback_api(self):
        constructor = Mock(return_value=object())
        fake = SimpleNamespace(
            Client=constructor,
            CallbackAPIVersion=SimpleNamespace(VERSION2="v2"),
        )
        with patch.object(app, "mqtt", fake):
            self.assertIsNotNone(app.create_mqtt_client())
        constructor.assert_called_once_with(
            callback_api_version="v2", client_id="digitalhouses-sync-app",
        )

    def test_on_connect_accepts_4_and_5_args_and_retains_metadata(self):
        for arguments in ((None, None, 0), (None, None, 0, None)):
            with self.subTest(arguments=arguments):
                client = Mock()
                app.on_connect(client, *arguments)
                self.assertEqual(client.publish.call_count, 4)
                published = client.publish.call_args_list
                for item in published:
                    self.assertEqual(item.kwargs, {"qos": 1, "retain": True})
                sync_call = next(c for c in published if c.args[0].endswith("/sync"))
                payload = json.loads(sync_call.args[1])
                self.assertEqual(payload["product_id"], "digitalhouses_sync_app")
                self.assertEqual(payload["repository"],
                                 "https://github.com/DigitalHouses/home-assistant-apps")
                self.assertEqual(client.subscribe.call_count, 4)

    def test_failure_reason_does_not_publish_or_subscribe(self):
        client = Mock()
        app.on_connect(client, None, None, 5)
        client.publish.assert_not_called()
        client.subscribe.assert_not_called()


if __name__ == "__main__":
    unittest.main()
