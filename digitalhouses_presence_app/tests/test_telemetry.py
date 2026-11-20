"""Presence App telemetry v1: privacy, consent, persistence, and failure isolation."""
import json
import os
import stat
import tempfile
import unittest
import uuid
from pathlib import Path
from urllib.error import HTTPError

from telemetry import (
    FAILURE_BACKOFF_SECONDS, HTTP_TIMEOUT_SECONDS, INTERVAL_SECONDS,
    JITTER_SECONDS, PRODUCT, TelemetryClient, TelemetryStateError,
)


class FakeTransport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.responses.pop(0) if self.responses else 204
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "telemetry.json"
        self.time = [1_798_000_000.0]

    def make(self, *, enabled=True, version="0.1.40", transport=None):
        return TelemetryClient(
            version=version, enabled=enabled, state_file=self.path,
            transport=transport or FakeTransport(), now_epoch=lambda: self.time[0],
        )

    def test_no_opt_in_creates_no_identity_and_no_traffic(self):
        transport = FakeTransport()
        client = self.make(enabled=False, transport=transport)
        self.assertFalse(self.path.exists())
        self.assertIsNone(client.state)
        self.assertFalse(client.tick())
        self.assertFalse(client.delete())
        self.assertEqual(transport.calls, [])

    def test_first_opt_in_sends_only_exact_private_fields_with_bearer(self):
        transport = FakeTransport(204)
        client = self.make(transport=transport)
        self.assertTrue(self.path.is_file())
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertTrue(client.tick())
        self.assertEqual(len(transport.calls), 1)
        call = transport.calls[0]
        self.assertEqual((call["method"], call["path"], call["timeout_seconds"]),
                         ("POST", "/v1/heartbeat", HTTP_TIMEOUT_SECONDS))
        body = call["payload"]
        self.assertEqual(body, {
            "schema": 1,
            "telemetry_policy_version": 1,
            "installation_id": client.state["installation_id"],
            "product": PRODUCT,
            "version": "0.1.40",
        })
        self.assertEqual(set(body), {"schema", "telemetry_policy_version",
                                     "installation_id", "product", "version"})
        self.assertNotIn(call["token"], json.dumps(body))
        self.assertEqual(len(bytes.fromhex(call["token"])), 32)
        self.assertEqual(uuid.UUID(body["installation_id"]).version, 4)
        self.assertNotIn("192.168.", json.dumps(body))
        self.assertNotIn("device_tracker", json.dumps(body))
        self.assertNotIn("gps", json.dumps(body))
        self.assertNotIn("mac", json.dumps(body))

    def test_restart_preserves_identity_and_suppresses_repeated_heartbeat(self):
        transport = FakeTransport()
        original = self.make(transport=transport)
        self.assertTrue(original.tick())
        uid = original.state["installation_id"]
        token = original.state["installation_token"]
        current = self.make(transport=transport)
        self.assertEqual(current.state["installation_id"], uid)
        self.assertEqual(current.state["installation_token"], token)
        self.assertFalse(current.tick())
        self.assertEqual(len(transport.calls), 1)
        self.assertGreaterEqual(current._interval(), INTERVAL_SECONDS - JITTER_SECONDS)
        self.assertLessEqual(current._interval(), INTERVAL_SECONDS + JITTER_SECONDS)
        self.time[0] += current._interval()
        self.assertTrue(current.tick())

    def test_new_release_heartbeat_even_with_prior_success(self):
        previous = self.make(transport=FakeTransport())
        self.assertTrue(previous.tick())
        transport = FakeTransport()
        upgraded = self.make(version="0.1.41", transport=transport)
        self.assertTrue(upgraded.tick())
        self.assertEqual(transport.calls[0]["payload"]["version"], "0.1.41")

    def test_network_failure_retries_after_backoff_without_blocking(self):
        transport = FakeTransport(TimeoutError("offline"), 204)
        client = self.make(transport=transport)
        self.assertFalse(client.tick())
        self.assertFalse(client.tick())
        self.time[0] += FAILURE_BACKOFF_SECONDS - 1
        self.assertFalse(client.tick())
        self.assertEqual(len(transport.calls), 1)
        self.time[0] += 1
        self.assertTrue(client.tick())
        self.assertEqual(len(transport.calls), 2)

    def test_http_422_diagnostic_and_retry_backoff(self):
        err = HTTPError("https://telemetry.digitalhouses.vip/v1/heartbeat",
                        422, "unsupported product", {}, None)
        transport = FakeTransport(err)
        client = self.make(transport=transport)
        with self.assertLogs("dh_presence_app.telemetry", level="WARNING") as logs:
            self.assertFalse(client.tick())
        output = "\n".join(logs.output)
        self.assertIn("HTTP 422", output)
        self.assertIn("product allowlist", output)
        self.assertNotIn("last_success_epoch", client.state)
        self.assertFalse(client.tick())
        self.assertEqual(len(transport.calls), 1)

    def test_http_failure_is_not_counted_as_success(self):
        transport = FakeTransport(422, 204)
        client = self.make(transport=transport)
        self.assertFalse(client.tick())
        self.assertNotIn("last_success_epoch", client.state)
        self.time[0] += FAILURE_BACKOFF_SECONDS
        self.assertTrue(client.tick())

    def test_locally_identified_nonrelease_build_does_not_report(self):
        transport = FakeTransport()
        client = self.make(version="0.1.40-local", transport=transport)
        self.assertFalse(client.tick())
        self.assertEqual(transport.calls, [])

    def test_corrupt_persisted_identity_fails_instead_of_faking_installation(self):
        bad_states = [
            "not-json", "[]",
            '{"schema_version":1,"installation_id":"fake","installation_token":"invalid"}',
            '{"schema_version":1,"installation_id":"00000000-0000-4000-8000-000000000000","installation_token":"1234"}',
        ]
        for bad in bad_states:
            with self.subTest(bad=bad):
                self.path.write_text(bad, encoding="utf-8")
                with self.assertRaises(TelemetryStateError):
                    self.make()
                self.assertEqual(self.path.read_text(encoding="utf-8"), bad)

    def test_erasure_posts_only_id_and_rotates_persistent_credentials(self):
        transport = FakeTransport(204)
        client = self.make(transport=transport)
        original = client.state["installation_id"]
        token = client.state["installation_token"]
        self.assertTrue(client.delete())
        self.assertEqual(transport.calls[0]["method"], "DELETE")
        self.assertEqual(transport.calls[0]["path"], "/v1/installation")
        self.assertEqual(transport.calls[0]["payload"], {
            "schema": 1, "installation_id": original, "product": PRODUCT,
        })
        self.assertEqual(transport.calls[0]["token"], token)
        self.assertNotEqual(client.state["installation_id"], original)
        self.assertNotEqual(client.state["installation_token"], token)
        reopened = self.make(transport=FakeTransport())
        self.assertEqual(reopened.state["installation_id"], client.state["installation_id"])

    def test_erasure_404_is_idempotent(self):
        err = HTTPError("https://telemetry.digitalhouses.vip/v1/installation",
                        404, "not found", {}, None)
        client = self.make(transport=FakeTransport(err))
        original = client.state["installation_id"]
        self.assertTrue(client.delete())
        self.assertNotEqual(client.state["installation_id"], original)

    def test_erasure_failure_does_not_rotate_identity(self):
        client = self.make(transport=FakeTransport(500))
        original = client.state["installation_id"]
        self.assertFalse(client.delete())
        self.assertEqual(client.state["installation_id"], original)

    def test_presence_runtime_keeps_running_without_consent(self):
        source = (Path(__file__).resolve().parents[1] / "rootfs/app/app.py").read_text(encoding="utf-8")
        self.assertIn('if options["telemetry_enabled"]:', source)
        self.assertIn('LOG.info("DigitalHouses telemetry disabled by operator; presence remains active")', source)
        self.assertIn("if telemetry_runner is not None:", source)
        self.assertIn("telemetry_runner.stop()", source)
        self.assertNotIn("Statistics collection consent not granted. Stopping", source)


if __name__ == "__main__":
    unittest.main()
