from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "rootfs" / "app"
sys.path.insert(0, str(APP_DIR))

from telemetry import PRODUCT, TelemetryClient


class FakeTransport:
    def __init__(self, status: int = 204, error: Exception | None = None) -> None:
        self.status = status
        self.error = error
        self.calls: list[dict] = []

    def request(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.status


class TelemetryTests(unittest.TestCase):
    def test_fresh_install_creates_persistent_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / "telemetry.json"
            first = TelemetryClient(
                enabled=False,
                version="0.1.10",
                state_file=state,
            )
            second = TelemetryClient(
                enabled=False,
                version="0.1.10",
                state_file=state,
            )
            self.assertEqual(first.installation_id, second.installation_id)
            self.assertEqual(first.installation_token, second.installation_token)
            self.assertGreaterEqual(len(bytes.fromhex(first.installation_token)), 32)

    def test_payload_is_exact_protocol_v1(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            client = TelemetryClient(
                enabled=False,
                version="0.1.10",
                state_file=Path(temp) / "telemetry.json",
            )
            self.assertEqual(
                client.payload(),
                {
                    "schema": 1,
                    "telemetry_policy_version": 1,
                    "installation_id": client.installation_id,
                    "product": "digitalhouses_internet_app",
                    "version": "0.1.10",
                },
            )

    def test_disabled_telemetry_sends_no_request(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            transport = FakeTransport()
            client = TelemetryClient(
                enabled=False,
                version="0.1.10",
                state_file=Path(temp) / "telemetry.json",
                transport=transport,
                now_epoch=lambda: 1000.0,
            )
            self.assertFalse(client.tick())
            self.assertEqual(transport.calls, [])

    def test_reenable_sends_immediate_heartbeat_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            now = {"value": 1000.0}
            state = Path(temp) / "telemetry.json"

            initial = TelemetryClient(
                enabled=True,
                version="0.1.11",
                state_file=state,
                transport=FakeTransport(),
                now_epoch=lambda: now["value"],
            )
            self.assertTrue(initial.tick())

            now["value"] += 60.0
            disabled_transport = FakeTransport()
            disabled = TelemetryClient(
                enabled=False,
                version="0.1.11",
                state_file=state,
                transport=disabled_transport,
                now_epoch=lambda: now["value"],
            )
            self.assertFalse(disabled.tick())
            self.assertEqual(disabled_transport.calls, [])

            now["value"] += 60.0
            reenabled_transport = FakeTransport()
            reenabled = TelemetryClient(
                enabled=True,
                version="0.1.11",
                state_file=state,
                transport=reenabled_transport,
                now_epoch=lambda: now["value"],
            )
            self.assertTrue(reenabled.tick())
            self.assertEqual(len(reenabled_transport.calls), 1)

            now["value"] += 60.0
            restarted_transport = FakeTransport()
            restarted = TelemetryClient(
                enabled=True,
                version="0.1.11",
                state_file=state,
                transport=restarted_transport,
                now_epoch=lambda: now["value"],
            )
            self.assertFalse(restarted.tick())
            self.assertEqual(restarted_transport.calls, [])

    def test_failed_reenable_keeps_backoff_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            now = {"value": 1000.0}
            state = Path(temp) / "telemetry.json"

            initial = TelemetryClient(
                enabled=True,
                version="0.1.11",
                state_file=state,
                transport=FakeTransport(),
                now_epoch=lambda: now["value"],
            )
            self.assertTrue(initial.tick())

            now["value"] += 60.0
            TelemetryClient(
                enabled=False,
                version="0.1.11",
                state_file=state,
                transport=FakeTransport(),
                now_epoch=lambda: now["value"],
            )

            now["value"] += 60.0
            failing_transport = FakeTransport(error=OSError("offline"))
            reenabled = TelemetryClient(
                enabled=True,
                version="0.1.11",
                state_file=state,
                transport=failing_transport,
                now_epoch=lambda: now["value"],
            )
            self.assertFalse(reenabled.tick())
            self.assertEqual(len(failing_transport.calls), 1)

            now["value"] += 60.0
            restarted_transport = FakeTransport()
            restarted = TelemetryClient(
                enabled=True,
                version="0.1.11",
                state_file=state,
                transport=restarted_transport,
                now_epoch=lambda: now["value"],
            )
            self.assertFalse(restarted.tick())
            self.assertEqual(restarted_transport.calls, [])

    def test_local_build_never_sends_production_telemetry(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            transport = FakeTransport()
            client = TelemetryClient(
                enabled=True,
                version="0.1.10-local",
                state_file=Path(temp) / "telemetry.json",
                transport=transport,
                now_epoch=lambda: 1000.0,
            )
            self.assertFalse(client.tick())
            self.assertEqual(transport.calls, [])

    def test_enabled_heartbeat_and_restart_do_not_storm(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            now = {"value": 1000.0}
            state = Path(temp) / "telemetry.json"
            first_transport = FakeTransport()
            first = TelemetryClient(
                enabled=True,
                version="0.1.10",
                state_file=state,
                transport=first_transport,
                now_epoch=lambda: now["value"],
            )
            self.assertTrue(first.tick())
            self.assertEqual(len(first_transport.calls), 1)
            call = first_transport.calls[0]
            self.assertEqual(call["method"], "POST")
            self.assertEqual(call["path"], "/v1/heartbeat")
            self.assertEqual(call["payload"]["product"], PRODUCT)
            self.assertEqual(call["token"], first.installation_token)

            restarted_transport = FakeTransport()
            restarted = TelemetryClient(
                enabled=True,
                version="0.1.10",
                state_file=state,
                transport=restarted_transport,
                now_epoch=lambda: now["value"] + 60.0,
            )
            self.assertFalse(restarted.tick())
            self.assertEqual(restarted_transport.calls, [])

    def test_version_change_reports_immediately_with_same_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            now = {"value": 1000.0}
            state = Path(temp) / "telemetry.json"
            old = TelemetryClient(
                enabled=True,
                version="0.1.10",
                state_file=state,
                transport=FakeTransport(),
                now_epoch=lambda: now["value"],
            )
            self.assertTrue(old.tick())
            installation_id = old.installation_id

            transport = FakeTransport()
            upgraded = TelemetryClient(
                enabled=True,
                version="0.1.11",
                state_file=state,
                transport=transport,
                now_epoch=lambda: now["value"] + 60.0,
            )
            self.assertTrue(upgraded.tick())
            self.assertEqual(upgraded.installation_id, installation_id)
            self.assertEqual(
                transport.calls[0]["payload"]["version"],
                "0.1.11",
            )

    def test_failure_is_isolated_and_backed_off(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            now = {"value": 1000.0}
            transport = FakeTransport(error=OSError("offline"))
            client = TelemetryClient(
                enabled=True,
                version="0.1.10",
                state_file=Path(temp) / "telemetry.json",
                transport=transport,
                now_epoch=lambda: now["value"],
            )
            self.assertFalse(client.tick())
            self.assertEqual(len(transport.calls), 1)
            now["value"] += 60.0
            self.assertFalse(client.tick())
            self.assertEqual(len(transport.calls), 1)

    def test_authenticated_delete_uses_same_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            transport = FakeTransport()
            client = TelemetryClient(
                enabled=False,
                version="0.1.10",
                state_file=Path(temp) / "telemetry.json",
                transport=transport,
            )
            self.assertTrue(client.delete())
            call = transport.calls[0]
            self.assertEqual(call["method"], "DELETE")
            self.assertEqual(call["path"], "/v1/installation")
            self.assertEqual(
                call["payload"],
                {
                    "schema": 1,
                    "installation_id": client.installation_id,
                    "product": PRODUCT,
                },
            )
            self.assertEqual(call["token"], client.installation_token)


if __name__ == "__main__":
    unittest.main()
