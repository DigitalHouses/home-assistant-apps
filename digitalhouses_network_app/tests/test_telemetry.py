"""Network App telemetry policy-v2 tests; HTTP calls are replaced by a fake."""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
import uuid
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "dh_network_telemetry", APP / "rootfs" / "app" / "telemetry.py"
)
assert SPEC and SPEC.loader
telemetry = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(telemetry)


class Transport:
    def __init__(self, status=204, error=None):
        self.status = status
        self.error = error
        self.calls = []

    def request(self, method, path, payload, token):
        self.calls.append((method, path, payload, token))
        if self.error is not None:
            raise self.error
        return self.status


class TestTelemetry(unittest.TestCase):
    def test_no_identity_or_heartbeat_without_consent(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / "telemetry.json"
            transport = Transport()
            client = telemetry.TelemetryClient("0.1.32", enabled=False,
                                               state_file=state, transport=transport)
            self.assertFalse(state.exists())
            self.assertFalse(client.tick())
            self.assertFalse(client.delete_installation())
            self.assertEqual(transport.calls, [])

    def test_exact_policy_v2_payload_minimizes_user_data(self):
        with tempfile.TemporaryDirectory() as temp:
            transport = Transport()
            state = Path(temp) / "telemetry.json"
            client = telemetry.TelemetryClient("0.1.32", enabled=True,
                                               state_file=state, transport=transport,
                                               now=lambda: 1000.0)
            self.assertTrue(client.tick())
            self.assertEqual(len(transport.calls), 1)
            method, path, payload, token = transport.calls[0]
            self.assertEqual((method, path), ("POST", "/v1/heartbeat"))
            self.assertEqual(payload, {
                "schema": 1, "telemetry_policy_version": 2,
                "installation_id": client.state["installation_id"],
                "product": "digitalhouses_network_app", "version": "0.1.32"
            })
            self.assertEqual(uuid.UUID(payload["installation_id"]).version, 4)
            self.assertGreaterEqual(len(bytes.fromhex(token)), 32)
            self.assertEqual(state.stat().st_mode & 0o777, 0o600)
            for forbidden in ("hostname", "device_id", "homeassistant_uuid", "mac",
                              "ipv4", "password", "country", "email", "router"):
                self.assertNotIn(forbidden, payload)

    def test_restart_same_identity_no_duplicate_heartbeat(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / "telemetry.json"
            first = telemetry.TelemetryClient(
                "0.1.32", enabled=True, state_file=state, transport=Transport(),
                now=lambda: 1000.0
            )
            self.assertTrue(first.tick())
            transport = Transport()
            again = telemetry.TelemetryClient(
                "0.1.32", enabled=True, state_file=state, transport=transport,
                now=lambda: 1060.0
            )
            self.assertEqual(again.state["installation_id"], first.state["installation_id"])
            self.assertEqual(again.state["installation_token"], first.state["installation_token"])
            self.assertFalse(again.tick())
            self.assertEqual(transport.calls, [])

    def test_new_version_reports_on_same_installation(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / "telemetry.json"
            client = telemetry.TelemetryClient(
                "0.1.32", enabled=True, state_file=state, transport=Transport(),
                now=lambda: 1000.0
            )
            self.assertTrue(client.tick())
            new_transport = Transport()
            upgraded = telemetry.TelemetryClient(
                "0.1.33", enabled=True, state_file=state, transport=new_transport,
                now=lambda: 1060.0
            )
            self.assertEqual(upgraded.state["installation_id"], client.state["installation_id"])
            self.assertTrue(upgraded.tick())
            self.assertEqual(new_transport.calls[0][2]["version"], "0.1.33")

    def test_failure_isolation_backoff_persists_across_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / "telemetry.json"
            failing = Transport(error=OSError("offline"))
            client = telemetry.TelemetryClient(
                "0.1.32", enabled=True, state_file=state, transport=failing,
                now=lambda: 1000.0
            )
            self.assertFalse(client.tick())
            self.assertEqual(len(failing.calls), 1)
            later_transport = Transport()
            later = telemetry.TelemetryClient(
                "0.1.32", enabled=True, state_file=state, transport=later_transport,
                now=lambda: 1100.0
            )
            self.assertFalse(later.tick())
            self.assertEqual(later_transport.calls, [])
            at_retry = telemetry.TelemetryClient(
                "0.1.32", enabled=True, state_file=state, transport=later_transport,
                now=lambda: 4600.0
            )
            self.assertTrue(at_retry.tick())
            self.assertEqual(len(later_transport.calls), 1)

    def test_invalid_state_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / "telemetry.json"
            state.write_text('{"schema_version":1,"installation_id":"bad"}', encoding="utf-8")
            original = state.read_text(encoding="utf-8")
            with self.assertRaises(telemetry.TelemetryStateError):
                telemetry.TelemetryClient("0.1.32", enabled=True, state_file=state)
            self.assertEqual(original, state.read_text(encoding="utf-8"))

    def test_authenticated_delete_rotates_identity_and_token(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / "telemetry.json"
            transport = Transport()
            client = telemetry.TelemetryClient("0.1.32", enabled=True,
                                               state_file=state, transport=transport)
            old_id = client.state["installation_id"]
            old_token = client.state["installation_token"]
            self.assertTrue(client.delete_installation())
            self.assertEqual(transport.calls[0], (
                "DELETE", "/v1/installation",
                {"schema": 1, "installation_id": old_id, "product": "digitalhouses_network_app"},
                old_token
            ))
            self.assertNotEqual(client.state["installation_id"], old_id)
            self.assertNotEqual(client.state["installation_token"], old_token)
            self.assertEqual(client.state, json.loads(state.read_text(encoding="utf-8")))

    def test_failed_delete_does_not_rotate(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / "telemetry.json"
            transport = Transport(status=401)
            client = telemetry.TelemetryClient("0.1.32", enabled=True,
                                               state_file=state, transport=transport)
            before = dict(client.state)
            self.assertFalse(client.delete_installation())
            self.assertEqual(client.state, before)

    def test_invalid_build_never_sends(self):
        with tempfile.TemporaryDirectory() as temp:
            transport = Transport()
            client = telemetry.TelemetryClient(
                "0.1.32-local", enabled=True,
                state_file=Path(temp) / "telemetry.json", transport=transport
            )
            # Local/dev suffixes are explicitly excluded even though they parse as semver.
            self.assertFalse(client.tick())
            self.assertEqual(transport.calls, [])

    def test_launcher_guards_core_runtime_before_start(self):
        launcher = (APP / "rootfs" / "run.sh").read_text(encoding="utf-8")
        self.assertIn("bashio::config.true 'telemetry_enabled'", launcher)
        self.assertIn("Statistics collection consent not granted. Stopping application.", launcher)
        self.assertLess(launcher.index("bashio::config.true 'telemetry_enabled'"),
                        launcher.index("python3 /app/mqtt_events.py &"))
        self.assertLess(launcher.index("bashio::config.true 'telemetry_enabled'"),
                        launcher.index("exec /usr/local/bin/dh-network"))
        self.assertIn("python3 /app/telemetry.py &", launcher)

    def test_app_consent_and_stats_registry_are_explicit(self):
        cfg = (APP / "config.yaml").read_text(encoding="utf-8")
        self.assertIn("telemetry_enabled: false", cfg)
        self.assertIn("telemetry_enabled: bool", cfg)
        repo = APP.parent
        registry = json.loads((repo / "digitalhouses-stats" /
                               "digitalhouses_stats" / "product_registry.json").read_text(encoding="utf-8"))
        product = next(x for x in registry["products"]
                       if x["id"] == "digitalhouses_network_app")
        self.assertIs(product["telemetry_allowed"], True)
        for language in ("ru", "en"):
            loc = (APP / "translations" / f"{language}.yaml").read_text(encoding="utf-8")
            self.assertIn("PRODUCT_TELEMETRY_POLICY.md", loc)
            self.assertIn("telemetry_enabled:", loc)


if __name__ == "__main__":
    unittest.main()
