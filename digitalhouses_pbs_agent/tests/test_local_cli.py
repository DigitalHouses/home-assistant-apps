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

    def test_rrd_uses_running_local_https_proxy_not_uninitialized_debug_cache(self):
        class Proc:
            stdout = json.dumps({"data": [
                {"time": 1795300000, "used": 124000000000},
                {"time": 1795301800, "used": 124500000000},
            ]})
        observed = []
        with patch("app.collector.os.environ", {"PROXMOX_DEBUG_API_CODE": "1", "LANG": "C"}):
            with patch("app.collector.subprocess.run", return_value=Proc()) as run:
                results = PBSClient().get_rrd("pbs-serzhan")
                observed.append(run.call_args)
        self.assertEqual(len(results), 2)
        argv, kwargs = observed[0].args[0], observed[0].kwargs
        self.assertEqual(argv, [
            "proxmox-backup-debug", "api", "get",
            "/admin/datastore/pbs-serzhan/rrd",
            "--timeframe", "month", "--cf", "AVERAGE",
            "--output-format", "json",
        ])
        self.assertNotIn("PROXMOX_DEBUG_API_CODE", kwargs["env"],
                         "standard PBS CLI must query running HTTPS cache")
        self.assertEqual(kwargs["env"]["LANG"], "C")
        self.assertEqual(kwargs["timeout"], 25)
        self.assertTrue(kwargs["check"])

    def test_rrd_proxy_rejects_bad_names_and_preserves_read_only_failure(self):
        pbs = PBSClient()
        for store in ("", "../outside", "a/b", "foo\nbar", "a" * 200):
            with self.subTest(store=store):
                with self.assertRaises(SourceError):
                    pbs.get_rrd(store)
        error = subprocess.CalledProcessError(
            255, "proxmox-backup-debug", stderr="connection refused"
        )
        with patch("app.collector.subprocess.run", side_effect=error):
            with self.assertRaisesRegex(SourceError, "PBS RRD HTTPS proxy failed.*connection refused"):
                pbs.get_rrd("pbs-serzhan")
        class Invalid:
            stdout = "not JSON"
        with patch("app.collector.subprocess.run", return_value=Invalid()):
            with self.assertRaisesRegex(SourceError, "invalid JSON"):
                pbs.get_rrd("pbs-serzhan")

    def test_nonzero_cli_error_does_not_become_success(self):
        with patch("app.collector.subprocess.run",
                   side_effect=subprocess.CalledProcessError(1, "proxmox-backup-debug")):
            with self.assertRaisesRegex(SourceError, "PBS local CLI failed"):
                PBSClient().get("version")

    def test_cli_error_includes_bounded_stderr_for_diagnostics(self):
        error = subprocess.CalledProcessError(
            2, "proxmox-backup-debug", stderr="task API error: unsupported option"
        )
        with patch("app.collector.subprocess.run", side_effect=error):
            with self.assertRaisesRegex(
                SourceError, r"exit 2.*task API error: unsupported option"
            ):
                PBSClient().get("nodes/localhost/tasks", limit=100)

    def test_native_manager_tasks_include_completed(self):
        class Done:
            stdout = '[{"upid":"UPID:pbs:1","worker_type":"backup","status":"OK","endtime":123}]'
        commands = []
        def execute(argv, **kwargs):
            commands.append((argv, kwargs))
            return Done()
        with patch("app.collector.subprocess.run", side_effect=execute):
            rows = PBSClient().task_list(limit=100)
        self.assertEqual(rows[0]["status"], "OK")
        self.assertEqual(commands[0][0], [
            "proxmox-backup-manager", "task", "list", "--all", "true",
            "--limit", "100", "--output-format", "json"
        ])
        self.assertEqual(commands[0][1]["timeout"], 20)

    def test_native_manager_task_failure_not_silent(self):
        error = subprocess.CalledProcessError(
            255, "proxmox-backup-manager", stderr="temporary task list unavailable"
        )
        with patch("app.collector.subprocess.run", side_effect=error):
            with self.assertRaisesRegex(
                SourceError, "PBS native task list failed \\(exit 255\\)"
            ):
                PBSClient().task_list()
    
    def test_native_manager_rejects_invalid_json(self):
        class Done:
            stdout = '{}'
        with patch("app.collector.subprocess.run", return_value=Done()):
            with self.assertRaisesRegex(SourceError, "invalid structure"):
                PBSClient().task_list()
    
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
