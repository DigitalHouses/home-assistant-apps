import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "rootfs" / "app"))

from telemetry import PRODUCT, TelemetryClient


class FakeTransport:
    def __init__(self, status=204):
        self.status = status
        self.calls = []

    def request(self, **kwargs):
        self.calls.append(kwargs)
        return self.status


class TelemetryTests(unittest.TestCase):
    def test_fresh_install_creates_persistent_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / "telemetry_state.json"
            client = TelemetryClient(
                enabled=False,
                version="0.1.0",
                state_file=state,
            )
            first_id = client.installation_id
            first_token = client.installation_token
            restored = TelemetryClient(
                enabled=False,
                version="0.1.0",
                state_file=state,
            )
            self.assertEqual(restored.installation_id, first_id)
            self.assertEqual(restored.installation_token, first_token)

    def test_disabled_telemetry_sends_no_request(self):
        with tempfile.TemporaryDirectory() as temp:
            transport = FakeTransport()
            client = TelemetryClient(
                enabled=False,
                version="0.1.0",
                state_file=Path(temp) / "telemetry_state.json",
                transport=transport,
                now_epoch=lambda: 1000,
            )
            self.assertFalse(client.tick())
            self.assertEqual(transport.calls, [])

    def test_enabled_heartbeat_uses_protocol_v1_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            transport = FakeTransport()
            client = TelemetryClient(
                enabled=True,
                version="0.1.0",
                state_file=Path(temp) / "telemetry_state.json",
                transport=transport,
                now_epoch=lambda: 1000,
            )
            self.assertTrue(client.tick())
            self.assertEqual(len(transport.calls), 1)
            call = transport.calls[0]
            self.assertEqual(call["method"], "POST")
            self.assertEqual(call["path"], "/v1/heartbeat")
            self.assertEqual(
                set(call["payload"]),
                {
                    "schema",
                    "telemetry_policy_version",
                    "installation_id",
                    "product",
                    "version",
                },
            )
            self.assertEqual(call["payload"]["product"], PRODUCT)

    def test_authenticated_delete_uses_same_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            transport = FakeTransport()
            client = TelemetryClient(
                enabled=False,
                version="0.1.0",
                state_file=Path(temp) / "telemetry_state.json",
                transport=transport,
            )
            installation_id = client.installation_id
            token = client.installation_token
            self.assertTrue(client.delete())
            call = transport.calls[0]
            self.assertEqual(call["method"], "DELETE")
            self.assertEqual(call["path"], "/v1/installation")
            self.assertEqual(call["payload"]["installation_id"], installation_id)
            self.assertEqual(call["token"], token)

    def test_upgrade_keeps_identity_and_sends_new_version(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / "telemetry_state.json"
            first_transport = FakeTransport()
            first = TelemetryClient(
                enabled=True,
                version="0.1.10",
                state_file=state,
                transport=first_transport,
                now_epoch=lambda: 1000,
            )
            self.assertTrue(first.tick())
            installation_id = first.installation_id
            token = first.installation_token

            upgraded_transport = FakeTransport()
            upgraded = TelemetryClient(
                enabled=True,
                version="0.1.11",
                state_file=state,
                transport=upgraded_transport,
                now_epoch=lambda: 1010,
            )
            self.assertEqual(upgraded.installation_id, installation_id)
            self.assertEqual(upgraded.installation_token, token)
            self.assertTrue(upgraded.tick())
            self.assertEqual(
                upgraded_transport.calls[0]["payload"]["version"],
                "0.1.11",
            )

    def test_restart_does_not_create_heartbeat_storm(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / "telemetry_state.json"
            first_transport = FakeTransport()
            first = TelemetryClient(
                enabled=True,
                version="0.1.11",
                state_file=state,
                transport=first_transport,
                now_epoch=lambda: 1000,
            )
            self.assertTrue(first.tick())

            restarted_transport = FakeTransport()
            restarted = TelemetryClient(
                enabled=True,
                version="0.1.11",
                state_file=state,
                transport=restarted_transport,
                now_epoch=lambda: 1100,
            )
            self.assertFalse(restarted.tick())
            self.assertEqual(restarted_transport.calls, [])

    def test_failed_heartbeat_uses_backoff(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / "telemetry_state.json"
            transport = FakeTransport(status=500)
            now = [1000.0]
            client = TelemetryClient(
                enabled=True,
                version="0.1.11",
                state_file=state,
                transport=transport,
                now_epoch=lambda: now[0],
            )
            self.assertFalse(client.tick())
            self.assertEqual(len(transport.calls), 1)

            now[0] = 1200.0
            self.assertFalse(client.tick())
            self.assertEqual(len(transport.calls), 1)

    def test_malformed_state_is_regenerated_safely(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / "telemetry_state.json"
            state.write_text("{broken", encoding="utf-8")
            client = TelemetryClient(
                enabled=False,
                version="0.1.11",
                state_file=state,
            )
            self.assertTrue(client.installation_id)
            self.assertGreaterEqual(len(bytes.fromhex(client.installation_token)), 32)


if __name__ == "__main__":
    unittest.main()
