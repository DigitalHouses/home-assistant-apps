"""Regression: HA Core proxy access is required to scan Aqara switches."""
from __future__ import annotations
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

import yaml

from aqara_switch.ha_registry import HARegistryClient


ROOT = Path(__file__).resolve().parents[1]


class HAPermissionsTest(unittest.TestCase):
    def test_manifest_grants_minimum_ha_api_and_mqtt(self):
        conf = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
        self.assertTrue(conf["homeassistant_api"], "Supervisor must permit Core WebSocket at explicit Scan")
        self.assertTrue(conf["hassio_api"], "Scan saves adopted switches to own App Options")
        self.assertEqual(conf["hassio_role"], "default", "Do not escalate Supervisor privileges")
        self.assertIn("mqtt:need", conf["services"])
        self.assertEqual(conf["boot"], "manual")
        self.assertEqual(conf["version"], "0.1.16")

    def test_registry_handshake_uses_supervisor_token_and_reads_both_registries(self):
        class FakeSocket:
            def __init__(self):
                self.sent = []
                self.messages = iter([
                    {"type":"auth_required", "ha_version":"2026.10.0"},
                    {"type":"auth_ok", "ha_version":"2026.10.0"},
                    {"id":1,"type":"result","success":True,"result":[]},
                    {"id":2,"type":"result","success":True,"result":[]},
                    {"id":3,"type":"result","success":True,"result":[]},
                ])
                self.closed = False

            def recv(self):
                return json.dumps(next(self.messages))

            def send(self, data):
                self.sent.append(json.loads(data))

            def close(self):
                self.closed = True

        socket = FakeSocket()
        fake_websocket = types.SimpleNamespace(create_connection=lambda *args, **kwargs: socket)
        with patch.dict(sys.modules, {"websocket": fake_websocket}):
            devices, areas, entities = HARegistryClient("test-token").fetch()
        self.assertEqual((devices, areas, entities), ([], [], []))
        self.assertEqual(socket.sent, [
            {"type":"auth","access_token":"test-token"},
            {"id":1,"type":"config/device_registry/list"},
            {"id":2,"type":"config/area_registry/list"},
            {"id":3,"type":"config/entity_registry/list"},
        ])
        self.assertTrue(socket.closed)

    def test_auth_invalid_does_not_return_fake_empty_registry(self):
        class FakeSocket:
            def __init__(self):
                self.messages = iter([
                    {"type":"auth_required","ha_version":"2026.10.0"},
                    {"type":"auth_invalid","message":"Invalid access"},
                ])
                self.closed = False
            def recv(self): return json.dumps(next(self.messages))
            def send(self, data): pass
            def close(self): self.closed = True

        sock = FakeSocket()
        fake_websocket = types.SimpleNamespace(create_connection=lambda *args,**kwargs:sock)
        with patch.dict(sys.modules, {"websocket":fake_websocket}):
            with self.assertRaisesRegex(ValueError,"HA WebSocket authorization failed"):
                HARegistryClient("test-token").fetch()
        self.assertTrue(sock.closed)


if __name__ == "__main__":
    unittest.main()
