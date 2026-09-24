from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

APP_DIR = Path(__file__).resolve().parents[1] / "rootfs" / "app"
sys.path.insert(0, str(APP_DIR))

from mqtt_compat import create_mqtt_client


class FakeClient:
    calls: list[tuple[tuple, dict]] = []

    def __init__(self, *args, **kwargs) -> None:
        self.calls.append((args, kwargs))


class MqttCompatTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeClient.calls.clear()

    def test_paho_1_client_uses_legacy_constructor(self) -> None:
        module = SimpleNamespace(Client=FakeClient)
        create_mqtt_client(module, client_id="dh_internet_app")
        args, kwargs = FakeClient.calls[-1]
        self.assertEqual(args, ())
        self.assertEqual(kwargs, {"client_id": "dh_internet_app"})

    def test_paho_2_client_uses_callback_api_v2(self) -> None:
        version2 = object()
        module = SimpleNamespace(
            Client=FakeClient,
            CallbackAPIVersion=SimpleNamespace(VERSION2=version2),
        )
        create_mqtt_client(module, client_id="dh_internet_app")
        args, kwargs = FakeClient.calls[-1]
        self.assertEqual(args, (version2,))
        self.assertEqual(kwargs, {"client_id": "dh_internet_app"})


if __name__ == "__main__":
    unittest.main()
