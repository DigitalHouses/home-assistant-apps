"""Candidate DH Sync policy-v2 telemetry client contract tests (no network)."""
from __future__ import annotations

import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

import app
from telemetry import (
    ContractDataError,
    FAILURE_BACKOFF_SECONDS,
    NORMAL_INTERVAL_SECONDS,
    PRODUCT,
    TELEMETRY_POLICY_VERSION,
    TelemetryClient,
)


class FakeTransport:
    def __init__(self, *, status=204, error=None):
        self.status, self.error, self.calls = status, error, []

    def request(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.status


class TelemetryTests(unittest.TestCase):
    def make_client(self, directory, *, version="0.6.2", enabled=True,
                    clock=None, transport=None):
        return TelemetryClient(
            enabled=enabled, version=version,
            state_file=Path(directory) / "telemetry.json",
            now_epoch=clock or (lambda: 100_000.0),
            transport=transport or FakeTransport(),
        )

    def test_identity_is_persistent_and_secret_never_in_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            one = self.make_client(directory)
            two = self.make_client(directory)
            self.assertEqual(one.installation_id, two.installation_id)
            self.assertEqual(one.installation_token, two.installation_token)
            self.assertEqual(uuid.UUID(one.installation_id).version, 4)
            self.assertGreaterEqual(len(bytes.fromhex(one.installation_token)), 32)
            self.assertEqual(set(one.payload()), {
                "schema", "telemetry_policy_version", "installation_id",
                "product", "version",
            })
            self.assertEqual(one.payload()["product"], PRODUCT)
            self.assertEqual(one.payload()["telemetry_policy_version"], 2)
            self.assertNotIn(one.installation_token, json.dumps(one.payload()))
            self.assertEqual((Path(directory) / "telemetry.json").stat().st_mode & 0o777, 0o600)

    def test_disabled_sends_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            transport = FakeTransport()
            client = self.make_client(directory, enabled=False, transport=transport)
            self.assertFalse(client.tick())
            self.assertEqual(transport.calls, [])

    def test_first_heartbeat_daily_and_upgrade(self):
        with tempfile.TemporaryDirectory() as directory:
            now = [100_000.0]
            transport = FakeTransport()
            new = self.make_client(directory, clock=lambda: now[0], transport=transport)
            self.assertTrue(new.tick())
            req = transport.calls[0]
            self.assertEqual(req["path"], "/v1/heartbeat")
            self.assertEqual(req["method"], "POST")
            self.assertEqual(req["payload"]["version"], "0.6.2")
            self.assertEqual(req["payload"]["schema"], 1)
            self.assertEqual(req["payload"]["telemetry_policy_version"], 2)
            self.assertEqual(req["timeout_seconds"], 5)
            self.assertFalse(new.tick())
            now[0] += NORMAL_INTERVAL_SECONDS + 1801
            self.assertTrue(new.tick())
            changed = self.make_client(directory, version="0.6.3",
                                       clock=lambda: now[0], transport=transport)
            self.assertEqual(new.installation_id, changed.installation_id)
            self.assertTrue(changed.tick())

    def test_network_error_does_not_interrupt_and_retries_later(self):
        with tempfile.TemporaryDirectory() as directory:
            now = [100_000.0]
            transport = FakeTransport(error=TimeoutError("network down"))
            client = self.make_client(directory, clock=lambda: now[0], transport=transport)
            self.assertFalse(client.tick())
            self.assertEqual(len(transport.calls), 1)
            now[0] += FAILURE_BACKOFF_SECONDS - 1
            self.assertFalse(client.tick())
            self.assertEqual(len(transport.calls), 1)
            now[0] += 2
            transport.error = None
            self.assertTrue(client.tick())
            self.assertEqual(len(transport.calls), 2)

    def test_authenticated_deletion_rotates_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            transport = FakeTransport()
            client = self.make_client(directory, transport=transport)
            self.assertTrue(client.tick())
            previous_id, previous_token = client.installation_id, client.installation_token
            self.assertTrue(client.delete())
            request = transport.calls[-1]
            self.assertEqual(request["method"], "DELETE")
            self.assertEqual(request["path"], "/v1/installation")
            self.assertEqual(request["payload"]["installation_id"], previous_id)
            self.assertEqual(request["token"], previous_token)
            self.assertNotEqual(client.installation_id, previous_id)
            self.assertNotEqual(client.installation_token, previous_token)
            restored = self.make_client(directory)
            self.assertEqual(restored.installation_id, client.installation_id)
            self.assertTrue(restored.tick())

    def test_development_version_never_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            transport = FakeTransport()
            client = self.make_client(directory, version="0.6.2-local",
                                      transport=transport)
            self.assertFalse(client.tick())
            self.assertEqual(transport.calls, [])

    def test_corrupted_existing_state_not_silently_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "telemetry.json"
            path.write_text("{broken", encoding="utf-8")
            with self.assertRaises(ContractDataError):
                self.make_client(directory)
            self.assertEqual(path.read_text(encoding="utf-8"), "{broken")

    def test_no_consent_blocks_start_without_mqtt_or_telemetry(self):
        with patch.dict(app.os.environ, {"TELEMETRY_ENABLED": "false"}):
            with patch.object(app, "create_mqtt_client") as mqtt_client:
                with patch.object(app, "TelemetryClient") as telemetry_client:
                    with self.assertRaises(SystemExit) as error:
                        app.main()
                    self.assertEqual(error.exception.code, 1)
                    mqtt_client.assert_not_called()
                    telemetry_client.assert_not_called()

    def test_consent_starts_runtime_and_runner(self):
        with patch.dict(app.os.environ, {
            "TELEMETRY_ENABLED": "true", "MQTT_HOST": "127.0.0.1",
        }):
            with patch.object(app, "TelemetryClient") as telemetry_cls, \
                 patch.object(app, "TelemetryRunner") as runner_cls, \
                 patch.object(app, "AutoSync") as sync_cls, \
                 patch.object(app, "make_server") as server_func, \
                 patch.object(app, "DashboardPublisher"), \
                 patch.object(app.threading, "Thread") as thread_cls, \
                 patch.object(app, "create_mqtt_client") as client_factory:
                sync_cls.return_value.root = Path("/tmp")
                sync_cls.return_value.data = Path("/tmp")
                client_factory.return_value = Mock()
                app.main()
                telemetry_cls.assert_called_once_with(enabled=True, version=app.VERSION)
                runner_cls.assert_called_once_with(telemetry_cls.return_value)
                runner_cls.return_value.start.assert_called_once()
                runner_cls.return_value.stop.assert_called_once()


if __name__ == "__main__":
    unittest.main()
