"""PBS Agent v0.1.1 telemetry contract: no network, no PBS service needed."""
from __future__ import annotations

import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

from app import main as main_module
from app.cli import _telemetry_delete, change_config
from app.config import load_config
from app.state import StateStore
from app.telemetry import (
    PRODUCT, TELEMETRY_POLICY_VERSION, JITTER_SECONDS,
    NORMAL_INTERVAL_SECONDS, FAILURE_BACKOFF_SECONDS,
    TelemetryClient,
)


class FakeTransport:
    def __init__(self, status=204, error=None):
        self.status, self.error, self.calls = status, error, []

    def request(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.status


class PBSTelemetryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state = StateStore(self.root / "state" / "telemetry.json")
        self.info = self.root / "BUILD_INFO"
        self.info.write_text(
            "version=0.1.1\nsource=digitalhouses_pbs_agent-v0.1.1\n"
            "commit=" + "a" * 40 + "\n", encoding="utf-8"
        )
        self.clock = [100_000.0]
        self.transport = FakeTransport()

    def client(self, *, enabled=True, version="0.1.1"):
        return TelemetryClient(
            enabled=enabled, version=version, state_store=self.state,
            build_info_path=self.info, transport=self.transport,
            now_epoch=lambda: self.clock[0]
        )

    def test_canonical_minimal_payload_and_persistent_identity(self):
        one = self.client()
        two = self.client()
        self.assertEqual(PRODUCT, "digitalhouses_pbs_agent")
        self.assertEqual(TELEMETRY_POLICY_VERSION, 2)
        self.assertEqual(one.installation_id, two.installation_id)
        self.assertEqual(one.installation_token, two.installation_token)
        self.assertEqual(uuid.UUID(one.installation_id).version, 4)
        self.assertGreaterEqual(len(bytes.fromhex(one.installation_token)), 32)
        self.assertEqual(one.payload(), {
            "schema": 1, "telemetry_policy_version": 2,
            "installation_id": one.installation_id,
            "product": PRODUCT, "version": "0.1.1",
        })
        self.assertNotIn(one.installation_token, json.dumps(one.payload()))
        self.assertEqual(self.state.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.state.path.parent.stat().st_mode & 0o777, 0o700)

    def test_first_heartbeat_and_jittered_daily_interval(self):
        client = self.client()
        self.assertTrue(client.tick())
        request = self.transport.calls[0]
        self.assertEqual(request["method"], "POST")
        self.assertEqual(request["path"], "/v1/heartbeat")
        self.assertEqual(request["timeout_seconds"], 5)
        self.assertEqual(request["token"], client.installation_token)
        self.assertEqual(request["payload"]["product"], PRODUCT)
        self.assertFalse(client.tick())
        self.assertLessEqual(abs(client._normal_interval() - NORMAL_INTERVAL_SECONDS), JITTER_SECONDS)
        self.clock[0] += NORMAL_INTERVAL_SECONDS + JITTER_SECONDS + 1
        self.assertTrue(client.tick())
        self.assertEqual(len(self.transport.calls), 2)
        another = self.client()
        self.assertFalse(another.tick())
        self.assertEqual(another.installation_id, client.installation_id)

    def test_fresh_version_is_reported_without_regenerating_uuid(self):
        client = self.client()
        self.assertTrue(client.tick())
        self.info.write_text(
            "version=0.1.2\nsource=digitalhouses_pbs_agent-v0.1.2\ncommit=" + "b"*40 + "\n")
        update = self.client(version="0.1.2")
        self.assertEqual(update.installation_id, client.installation_id)
        self.assertTrue(update.tick())
        self.assertEqual(self.transport.calls[-1]["payload"]["version"], "0.1.2")

    def test_dev_and_corrupt_build_never_send(self):
        for text in (
            "",
            "version=0.1.1\nsource=main\ncommit=" + "c"*40 + "\n",
            "version=0.1.1\nsource=digitalhouses_pbs_agent-v0.1.1\ncommit=invalid\n",
            "version=0.1.0\nsource=digitalhouses_pbs_agent-v0.1.0\ncommit=" + "c"*40 + "\n",
        ):
            self.info.write_text(text)
            self.assertFalse(self.client().tick())
        self.assertEqual(self.transport.calls, [])

    def test_disabled_client_never_sends(self):
        self.assertFalse(self.client(enabled=False).tick())
        self.assertEqual(self.transport.calls, [])

    def test_failure_backoff_without_pbs_impact(self):
        self.transport.error = TimeoutError("offline")
        client = self.client()
        self.assertFalse(client.tick())
        self.clock[0] += FAILURE_BACKOFF_SECONDS - 1
        self.assertFalse(client.tick())
        self.assertEqual(len(self.transport.calls), 1)
        self.clock[0] += 2
        self.transport.error = None
        self.assertTrue(client.tick())
        self.assertEqual(len(self.transport.calls), 2)

    def test_422_retries_not_flood(self):
        self.transport.status = 422
        client = self.client()
        self.assertFalse(client.tick())
        self.assertFalse(client.tick())
        self.assertEqual(len(self.transport.calls), 1)
        self.clock[0] += FAILURE_BACKOFF_SECONDS + 1
        self.transport.status = 204
        self.assertTrue(client.tick())

    def test_delete_rotates_identity_and_identity_is_persisted(self):
        client = self.client()
        self.assertTrue(client.tick())
        old_id, old_token = client.installation_id, client.installation_token
        self.assertTrue(client.delete())
        self.assertEqual(self.transport.calls[-1]["method"], "DELETE")
        self.assertEqual(self.transport.calls[-1]["path"], "/v1/installation")
        self.assertEqual(self.transport.calls[-1]["payload"]["installation_id"], old_id)
        self.assertEqual(self.transport.calls[-1]["token"], old_token)
        self.assertNotEqual(client.installation_id, old_id)
        self.assertNotEqual(client.installation_token, old_token)
        self.assertEqual(self.client().installation_id, client.installation_id)
        self.assertTrue(self.client().tick())

    def test_failed_delete_leaves_identity_intact(self):
        client = self.client()
        old_id, old_token = client.installation_id, client.installation_token
        self.transport.error = TimeoutError()
        self.assertFalse(client.delete())
        self.assertEqual(client.installation_id, old_id)
        self.assertEqual(self.client().installation_token, old_token)

    def test_existing_corrupt_state_is_not_overwritten(self):
        self.state.path.parent.mkdir(parents=True, exist_ok=True)
        for original in ("{bad", json.dumps({"schema_version":1,
            "installation_id": "invalid", "installation_token": "00" * 32})):
            self.state.path.write_text(original)
            with self.assertRaises(ValueError):
                self.client()
            self.assertEqual(self.state.path.read_text(), original)

    def test_legacy_ini_missing_consent_stops_before_mqtt_or_network(self):
        config = self.root / "legacy.conf"
        config.write_text(
            "[general]\nlog_level=info\n[mqtt]\nhost=broker\n[pbs]\ndatastores=pbs-home\n")
        self.assertFalse(load_config(config).telemetry_enabled)
        with patch("app.main.Publisher") as pub, patch("app.main.TelemetryClient") as telemetry:
            result = main_module.run(config, self.root / "work")
            self.assertEqual(result, 0)
            pub.assert_not_called()
            telemetry.assert_not_called()
        self.assertFalse((self.root / "work").exists())

    def test_native_single_switch_and_invalid_config(self):
        config = self.root / "legacy.conf"
        config.write_text(
            "[general]\nlog_level=info\n[mqtt]\nhost=broker\n[pbs]\ndatastores=pbs-home\n")
        self.assertFalse(load_config(config).telemetry_enabled)
        with patch("app.cli._service_state", return_value="inactive"):
            self.assertEqual(change_config(config, ["telemetry_enabled=true"]), "CHANGED")
            self.assertEqual(change_config(config, ["telemetry_enabled=true"]), "UNCHANGED")
        self.assertTrue(load_config(config).telemetry_enabled)
        with self.assertRaises(ValueError):
            change_config(config, ["telemetry_enabled=maybe"], restart=False)
        self.assertTrue(load_config(config).telemetry_enabled)

    def test_cli_deletion_restarts_only_own_service(self):
        self.client()
        with patch("app.cli.STATE_DIR", self.state.path.parent), \
             patch("app.cli._service_state", return_value="active"), \
             patch("app.cli._read_version", return_value="0.1.1"), \
             patch("app.cli.TelemetryClient") as client_cls, \
             patch("app.cli.subprocess.run") as runs:
            client_cls.return_value.delete.return_value = True
            self.assertEqual(_telemetry_delete(), 0)
            self.assertEqual([c.args[0][:2] for c in runs.call_args_list], [
                ["systemctl","stop"],["systemctl","start"]
            ])
            client_cls.return_value.delete.assert_called_once()

    def test_installer_requires_legacy_activation_before_stopping_service(self):
        installer = (Path(__file__).resolve().parents[1] / "install.sh").read_text()
        self.assertIn("telemetry_enabled=true", installer)
        self.assertLess(installer.index("if cfg.telemetry_enabled"), installer.index("if systemctl is-active --quiet"))

if __name__ == "__main__":
    unittest.main()
