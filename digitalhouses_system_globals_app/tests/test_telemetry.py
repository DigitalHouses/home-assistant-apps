"""Local-only protocol and lifecycle tests. No actual telemetry is sent."""
import json
import stat
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from telemetry import (
    TelemetryClient, UrllibTelemetryTransport, ContractDataError,
    PRODUCT, NORMAL_INTERVAL_SECONDS, JITTER_SECONDS, FAILURE_BACKOFF_SECONDS,
)


class Transport:
    def __init__(self, status=204):
        self.status = status
        self.calls = []
        self.error = None

    def request(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.status


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "telemetry.json"
        self.now = 100000.0
        self.transport = Transport()

    def client(self, enabled=True, version="0.1.0"):
        return TelemetryClient(enabled=enabled, version=version,
                               state_file=self.path, transport=self.transport,
                               now_epoch=lambda: self.now)

    def test_protocol_and_credentials(self):
        c = self.client()
        self.assertTrue(c.tick())
        self.assertEqual(uuid.UUID(c.installation_id).version, 4)
        self.assertEqual(len(bytes.fromhex(c.installation_token)), 32)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(self.transport.calls, [{
            "method": "POST", "path": "/v1/heartbeat",
            "payload": {"schema": 1, "telemetry_policy_version": 2,
                        "installation_id": c.installation_id, "product": PRODUCT,
                        "version": "0.1.0"},
            "token": c.installation_token, "timeout_seconds": 5.0,
        }])

    def test_delivery_status_tracks_completed_attempts(self):
        c=self.client()
        self.assertEqual(c.delivery_status,"unknown")
        self.transport.status=503
        self.assertFalse(c.tick())
        self.assertEqual(c.delivery_status,"warning")
        self.transport.status=204
        self.now+=FAILURE_BACKOFF_SECONDS+1
        self.assertTrue(c.tick())
        self.assertEqual(c.delivery_status,"ok")
        self.assertEqual(self.client(enabled=False).delivery_status,"disabled")

    def test_restart_upgrade_and_cadence(self):
        c = self.client()
        self.assertTrue(c.tick())
        interval = c._normal_interval()
        self.assertGreaterEqual(interval, NORMAL_INTERVAL_SECONDS-JITTER_SECONDS)
        self.assertLessEqual(interval, NORMAL_INTERVAL_SECONDS+JITTER_SECONDS)
        self.now += 1
        r = self.client()
        self.assertEqual((r.installation_id, r.installation_token),
                         (c.installation_id, c.installation_token))
        self.assertTrue(r.tick())
        self.assertFalse(r.tick())
        self.now += interval-1
        self.assertFalse(r.tick())
        self.now += 1
        self.assertTrue(r.tick())
        self.now += 1
        upgraded = self.client(version="0.1.3")
        self.assertEqual(upgraded.installation_id, c.installation_id)
        self.assertTrue(upgraded.tick())
        self.assertFalse(upgraded.tick())

    def test_disabled_and_local_build_do_not_send(self):
        self.assertFalse(self.client(enabled=False).tick())
        self.assertFalse(self.client(version="0.1.0-local").tick())
        self.assertEqual(self.transport.calls, [])

    def test_transport_failure_retries_hourly_in_same_process(self):
        c = self.client()
        self.transport.error = OSError("offline")
        self.assertFalse(c.tick())
        self.now += FAILURE_BACKOFF_SECONDS-1
        self.assertFalse(c.tick())
        self.assertEqual(len(self.transport.calls), 1)
        self.transport.error = None
        self.now += 1
        self.assertTrue(c.tick())
        self.assertFalse(c.tick())

    def test_restart_after_failed_422_tries_immediately(self):
        c = self.client()
        self.transport.status = 422
        self.assertFalse(c.tick())
        self.assertFalse(c.tick())
        self.now += 60
        self.transport.status = 204
        r = self.client()
        self.assertEqual(r.installation_id, c.installation_id)
        self.assertEqual(r.installation_token, c.installation_token)
        self.assertTrue(r.tick())
        self.assertFalse(r.tick())
        self.assertEqual(len(self.transport.calls), 2)

    def test_failed_restart_after_success_still_backs_off(self):
        c = self.client()
        self.assertTrue(c.tick())
        r = self.client()
        self.transport.status = 503
        self.assertFalse(r.tick())
        self.assertFalse(r.tick())
        self.now += FAILURE_BACKOFF_SECONDS-1
        self.assertFalse(r.tick())
        self.now += 1
        self.transport.status = 204
        self.assertTrue(r.tick())
        self.assertEqual(len(self.transport.calls), 3)

    def test_delete_rotates_identity_and_retains_consent(self):
        c = self.client()
        self.assertTrue(c.tick())
        old = c.installation_id, c.installation_token
        self.assertTrue(c.delete())
        call = self.transport.calls[-1]
        self.assertEqual(call["method"], "DELETE")
        self.assertEqual(call["path"], "/v1/installation")
        self.assertEqual(call["token"], old[1])
        self.assertEqual(call["payload"]["installation_id"], old[0])
        self.assertNotEqual(c.installation_id, old[0])
        self.assertNotEqual(c.installation_token, old[1])
        self.assertTrue(json.loads(self.path.read_text())["telemetry_enabled"])
        self.assertTrue(self.client().tick())

    def test_failed_delete_preserves_identity(self):
        c = self.client()
        old = c.installation_id, c.installation_token
        self.transport.status = 403
        self.assertFalse(c.delete())
        self.assertEqual((c.installation_id, c.installation_token), old)

    def test_http_404_delete_is_idempotent(self):
        c = TelemetryClient(enabled=True, version="0.1.0", state_file=self.path,
                            transport=UrllibTelemetryTransport(), now_epoch=lambda: self.now)
        old = c.installation_id
        with patch("telemetry.urllib.request.urlopen", side_effect=HTTPError(
                "https://telemetry.digitalhouses.vip/v1/installation",404,"Not found",{},None)):
            self.assertTrue(c.delete())
        self.assertNotEqual(c.installation_id, old)

    def test_corrupt_identity_is_not_overwritten(self):
        self.path.write_text("{}")
        with self.assertRaises(ContractDataError):
            self.client()
        self.assertEqual(self.path.read_text(), "{}")

    def test_service_denied_consent_does_not_initialize_runtime(self):
        import service
        with patch.object(service.Path, "read_text", return_value=json.dumps({
                "require_z2m": True, "telemetry_enabled": False
                })), patch.object(service, "Engine") as engine, patch.object(service, "serve") as serve:
            service.main()
            engine.assert_not_called()
            serve.assert_not_called()


if __name__ == "__main__":
    unittest.main()
