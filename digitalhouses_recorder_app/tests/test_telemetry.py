from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

APP_DIR = (
    Path(__file__).resolve().parents[1]
    / "rootfs"
    / "app"
)
sys.path.insert(0, str(APP_DIR))

from telemetry import PRODUCT, TelemetryClient


class FakeTransport:
    def __init__(
        self,
        status: int = 204,
        error: Exception | None = None,
    ) -> None:
        self.status = status
        self.error = error
        self.calls: list[dict] = []

    def request(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.status


class TelemetryTests(unittest.TestCase):
    def test_identity_persists_across_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / "telemetry.json"
            first = TelemetryClient(
                enabled=False,
                version="0.1.15",
                state_file=state,
            )
            second = TelemetryClient(
                enabled=False,
                version="0.1.15",
                state_file=state,
            )
            self.assertEqual(
                first.installation_id,
                second.installation_id,
            )
            self.assertEqual(
                first.installation_token,
                second.installation_token,
            )
            self.assertGreaterEqual(
                len(
                    bytes.fromhex(
                        first.installation_token
                    )
                ),
                32,
            )

    def test_payload_is_exact_protocol_v1(self):
        with tempfile.TemporaryDirectory() as temp:
            client = TelemetryClient(
                enabled=False,
                version="0.1.15",
                state_file=(
                    Path(temp) / "telemetry.json"
                ),
            )
            self.assertEqual(
                client.payload(),
                {
                    "schema": 1,
                    "telemetry_policy_version": 1,
                    "installation_id": (
                        client.installation_id
                    ),
                    "product": (
                        "digitalhouses_recorder_app"
                    ),
                    "version": "0.1.15",
                },
            )

    def test_default_disabled_state_sends_nothing(self):
        with tempfile.TemporaryDirectory() as temp:
            transport = FakeTransport()
            client = TelemetryClient(
                enabled=False,
                version="0.1.15",
                state_file=(
                    Path(temp) / "telemetry.json"
                ),
                transport=transport,
                now_epoch=lambda: 1000.0,
            )
            self.assertFalse(client.tick())
            self.assertEqual(transport.calls, [])

    def test_new_release_reports_immediately_with_same_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            now = {"value": 1000.0}
            state = Path(temp) / "telemetry.json"
            old = TelemetryClient(
                enabled=True,
                version="0.1.15",
                state_file=state,
                transport=FakeTransport(),
                now_epoch=lambda: now["value"],
            )
            self.assertTrue(old.tick())
            installation_id = old.installation_id
            token = old.installation_token

            transport = FakeTransport()
            upgraded = TelemetryClient(
                enabled=True,
                version="0.1.16",
                state_file=state,
                transport=transport,
                now_epoch=lambda: (
                    now["value"] + 60.0
                ),
            )
            self.assertTrue(upgraded.tick())
            self.assertEqual(
                upgraded.installation_id,
                installation_id,
            )
            self.assertEqual(
                upgraded.installation_token,
                token,
            )
            self.assertEqual(
                transport.calls[0]["payload"][
                    "version"
                ],
                "0.1.16",
            )

    def test_disable_stops_future_heartbeat(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / "telemetry.json"
            enabled = TelemetryClient(
                enabled=True,
                version="0.1.15",
                state_file=state,
                transport=FakeTransport(),
                now_epoch=lambda: 1000.0,
            )
            self.assertTrue(enabled.tick())

            transport = FakeTransport()
            disabled = TelemetryClient(
                enabled=False,
                version="0.1.15",
                state_file=state,
                transport=transport,
                now_epoch=lambda: 100000.0,
            )
            self.assertFalse(disabled.tick())
            self.assertEqual(transport.calls, [])

    def test_failure_is_isolated_and_backed_off(self):
        with tempfile.TemporaryDirectory() as temp:
            now = {"value": 1000.0}
            transport = FakeTransport(
                error=OSError("offline")
            )
            client = TelemetryClient(
                enabled=True,
                version="0.1.15",
                state_file=(
                    Path(temp) / "telemetry.json"
                ),
                transport=transport,
                now_epoch=lambda: now["value"],
            )
            self.assertFalse(client.tick())
            self.assertEqual(
                len(transport.calls),
                1,
            )
            now["value"] += 60.0
            self.assertFalse(client.tick())
            self.assertEqual(
                len(transport.calls),
                1,
            )

    def test_unreleased_build_never_sends(self):
        with tempfile.TemporaryDirectory() as temp:
            transport = FakeTransport()
            client = TelemetryClient(
                enabled=True,
                version="0.1.15-local",
                state_file=(
                    Path(temp) / "telemetry.json"
                ),
                transport=transport,
                now_epoch=lambda: 1000.0,
            )
            self.assertFalse(client.tick())
            self.assertEqual(transport.calls, [])

    def test_authenticated_delete_uses_same_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            transport = FakeTransport()
            client = TelemetryClient(
                enabled=False,
                version="0.1.15",
                state_file=(
                    Path(temp) / "telemetry.json"
                ),
                transport=transport,
            )
            self.assertTrue(client.delete())
            call = transport.calls[0]
            self.assertEqual(call["method"], "DELETE")
            self.assertEqual(
                call["path"],
                "/v1/installation",
            )
            self.assertEqual(
                call["payload"],
                {
                    "schema": 1,
                    "installation_id": (
                        client.installation_id
                    ),
                    "product": PRODUCT,
                },
            )
            self.assertEqual(
                call["token"],
                client.installation_token,
            )

    def test_state_file_contains_no_product_metrics(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / "telemetry.json"
            TelemetryClient(
                enabled=False,
                version="0.1.15",
                state_file=state,
            )
            data = json.loads(
                state.read_text(encoding="utf-8")
            )
            forbidden = {
                "db_host",
                "db_name",
                "db_username",
                "hostname",
                "ip",
                "storage_path",
                "country",
            }
            self.assertTrue(
                forbidden.isdisjoint(data)
            )


if __name__ == "__main__":
    unittest.main()
