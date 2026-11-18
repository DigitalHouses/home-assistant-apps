"""DigitalHouses Stats telemetry consent, identity, and safety regression."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import types
import unittest
from unittest.mock import Mock, patch

import yaml

from aqara_switch.runtime import Application
from aqara_switch.telemetry import ContractDataError, TelemetryClient


ROOT = Path(__file__).resolve().parents[1]


class FakeTransport:
    def __init__(self, status=204, error=None):
        self.status, self.error, self.calls = status, error, []

    def request(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.status


class FakeMQTT:
    def __init__(self, **kwargs):
        self.published = []

    def will_set(self, *args, **kwargs): pass
    def reconnect_delay_set(self, **kwargs): pass
    def publish(self, *args, **kwargs):
        self.published.append((args, kwargs))
        return types.SimpleNamespace(rc=0)
    def subscribe(self, *args, **kwargs): return (0, 1)


class TelemetryTests(unittest.TestCase):
    def test_configuration_defaults_opt_in_and_keeps_manual_control(self):
        config = yaml.safe_load((ROOT / "config.yaml").read_text())
        self.assertFalse(config["options"]["telemetry_enabled"])
        self.assertEqual(config["schema"]["telemetry_enabled"], "bool")
        self.assertEqual(config["boot"], "manual")
        self.assertEqual(config["version"], "0.1.18")

    def test_disabled_legacy_lighting_creates_no_telemetry_identity(self):
        for value in (False, None):
            with TemporaryDirectory() as td:
                options = Mock()
                options.read.return_value = {"switches": "[]", "telemetry_enabled": value}
                with patch("aqara_switch.runtime.TelemetryClient") as telemetry:
                    app = Application(
                        types.SimpleNamespace(Client=FakeMQTT), options=options,
                        registry=Mock(), last_scan_path=Path(td)/"scan.json",
                        version="0.1.18",
                    )
                    self.assertIsNone(app.telemetry)
                    self.assertIsNone(app.telemetry_runner)
                    telemetry.assert_not_called()
                    self.assertEqual(options.write.call_count, 0)

    def test_enabled_uses_only_one_telemetry_runner(self):
        options = Mock()
        options.read.return_value = {"switches": "[]", "telemetry_enabled": True}
        with TemporaryDirectory() as td, (
            patch("aqara_switch.runtime.TelemetryClient") as telemetry,
            patch("aqara_switch.runtime.TelemetryRunner") as runner,
        ):
            app = Application(
                types.SimpleNamespace(Client=FakeMQTT), options=options,
                registry=Mock(), last_scan_path=Path(td)/"scan.json",
                version="0.1.18",
            )
            telemetry.assert_called_once_with(enabled=True, version="0.1.18")
            runner.assert_called_once_with(telemetry.return_value)
            self.assertIs(app.telemetry_runner, runner.return_value)

    def test_identity_payload_and_no_restart_storm(self):
        with TemporaryDirectory() as td:
            path = Path(td)/"telemetry.json"
            transport = FakeTransport()
            t = TelemetryClient(enabled=True, version="0.1.18",
                                state_file=path, transport=transport,
                                now_epoch=lambda: 1000.0)
            self.assertEqual(t.payload(), {
                "schema": 1, "telemetry_policy_version": 2,
                "installation_id": t.installation_id,
                "product": "digitalhouses_aqara_switch_app",
                "version": "0.1.18",
            })
            self.assertEqual(len(bytes.fromhex(t.installation_token)), 32)
            self.assertTrue(t.tick())
            self.assertFalse(t.tick())
            self.assertEqual(len(transport.calls), 1)
            self.assertEqual(transport.calls[0]["path"], "/v1/heartbeat")
            self.assertEqual(transport.calls[0]["method"], "POST")
            self.assertNotIn(t.installation_token, json.dumps(t.payload()))
            restored = TelemetryClient(enabled=True, version="0.1.18",
                                       state_file=path, transport=transport,
                                       now_epoch=lambda: 1100.0)
            self.assertEqual(restored.installation_id, t.installation_id)
            self.assertFalse(restored.tick())

    def test_version_upgrade_uses_same_identity(self):
        with TemporaryDirectory() as td:
            path = Path(td)/"telemetry.json"
            first = TelemetryClient(enabled=True, version="0.1.18",
                                    state_file=path, transport=FakeTransport(),
                                    now_epoch=lambda: 1000)
            self.assertTrue(first.tick())
            transport = FakeTransport()
            upgraded = TelemetryClient(enabled=True, version="0.1.19",
                                       state_file=path, transport=transport,
                                       now_epoch=lambda: 1500)
            self.assertTrue(upgraded.tick())
            self.assertEqual(upgraded.installation_id, first.installation_id)
            self.assertEqual(transport.calls[0]["payload"]["version"], "0.1.19")

    def test_network_error_is_backed_off_and_does_not_crash(self):
        with TemporaryDirectory() as td:
            transport = FakeTransport(error=OSError("offline"))
            t = TelemetryClient(enabled=True, version="0.1.18",
                                state_file=Path(td)/"telemetry.json",
                                transport=transport, now_epoch=lambda: 1000)
            self.assertFalse(t.tick())
            self.assertFalse(t.tick())
            self.assertEqual(len(transport.calls), 1)

    def test_authenticated_deletion_rotates_pseudonym(self):
        with TemporaryDirectory() as td:
            path = Path(td)/"telemetry.json"
            transport = FakeTransport()
            t = TelemetryClient(enabled=True, version="0.1.18",
                                state_file=path, transport=transport)
            before = (t.installation_id, t.installation_token)
            self.assertTrue(t.delete())
            self.assertEqual(transport.calls[0]["path"], "/v1/installation")
            self.assertEqual(transport.calls[0]["payload"]["installation_id"], before[0])
            self.assertNotEqual(before, (t.installation_id, t.installation_token))
            self.assertEqual(json.loads(path.read_text())["installation_id"], t.installation_id)

    def test_corrupt_identity_never_replaced_silently(self):
        with TemporaryDirectory() as td:
            path = Path(td)/"telemetry.json"
            path.write_text(json.dumps({
                "schema_version": 1, "installation_id": "invalid",
                "installation_token": "1f"*32, "telemetry_enabled": True,
            }))
            with self.assertRaises(ContractDataError):
                TelemetryClient(enabled=True, version="0.1.18", state_file=path)

    def test_local_version_does_not_report(self):
        with TemporaryDirectory() as td:
            transport = FakeTransport()
            t = TelemetryClient(enabled=True, version="0.1.18-local",
                                state_file=Path(td)/"telemetry.json", transport=transport)
            self.assertFalse(t.tick())
            self.assertEqual(transport.calls, [])


if __name__ == "__main__":
    unittest.main()
