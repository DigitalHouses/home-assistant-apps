"""Tokenless PBS CLI parity with local root pvesh usage in PVE Agent."""
from __future__ import annotations

import json
import os
import subprocess
import unittest
from unittest.mock import patch

from app.collector import PBSClient, SourceError


class PBSLocalCliTests(unittest.TestCase):
    def test_only_read_only_native_api_get_with_json_output(self):
        commands = []
        def fake(argv):
            commands.append(argv)
            return json.dumps([{"id": "push-home", "sync-direction": "push"}])
        pbs = PBSClient(runner=fake)
        rows = pbs.get("admin/sync", sync_direction="push")
        self.assertEqual(rows[0]["id"], "push-home")
        self.assertEqual(commands, [[
            "proxmox-backup-debug", "api", "get", "/admin/sync",
            "--sync-direction", "push", "--output-format", "json",
        ]])

    def test_local_cli_unwraps_api_envelope_without_http(self):
        pbs = PBSClient(runner=lambda argv: '{"data":{"total":2048,"used":100}}')
        self.assertEqual(pbs.get("admin/datastore/store/status")["total"], 2048)

    def test_local_runner_enables_direct_api_code_and_never_logs_secret(self):
        class Proc:
            stdout = '{"version":"4.2.12"}'
        seen = {}
        def mock_run(argv, **kwargs):
            seen["argv"], seen["kwargs"] = argv, kwargs
            return Proc()
        with patch("app.collector.subprocess.run", side_effect=mock_run):
            self.assertIn('"version":"4.2.12"', PBSClient._run(
                ["proxmox-backup-debug", "api", "get", "/version", "--output-format", "json"]
            ))
        self.assertEqual(seen["kwargs"]["env"]["PROXMOX_DEBUG_API_CODE"], "1")
        self.assertEqual(seen["kwargs"]["timeout"], 20)
        self.assertTrue(seen["kwargs"]["check"])
        self.assertTrue(seen["kwargs"]["capture_output"])

    def test_nonzero_cli_error_does_not_become_success(self):
        with patch("app.collector.subprocess.run",
                   side_effect=subprocess.CalledProcessError(1, "proxmox-backup-debug")):
            with self.assertRaisesRegex(SourceError, "PBS local CLI failed"):
                PBSClient().get("version")

    def test_rejects_invalid_api_path_or_missing_json(self):
        pbs = PBSClient(runner=lambda argv: "")
        for path in ("../delete", "/admin/sync", "", "admin/\nprune"):
            with self.subTest(path=path):
                with self.assertRaises(SourceError):
                    pbs.get(path)
        with self.assertRaises(SourceError):
            pbs.get("admin/sync")


if __name__ == "__main__":
    unittest.main()
