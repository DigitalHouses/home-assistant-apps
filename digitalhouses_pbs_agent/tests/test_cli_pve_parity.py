"""Golden-output tests: current PVE Agent is the shared operational CLI/UI source."""
from __future__ import annotations

import contextlib
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import re
import stat
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app import cli


REPO = Path(__file__).resolve().parents[2]
PVE_CLI = (REPO / "digitalhouses_pve_agent/app/cli.py").read_text(encoding="utf-8")
PVE_VIEW = (REPO / "digitalhouses_pve_agent/dashboards/ru/10_pve_proxmox.yaml").read_text(encoding="utf-8")
PBS_VIEW_PATH = REPO / "digitalhouses_pbs_agent/dashboards/ru/13_pbs.yaml"


def run_main(args: list[str]) -> tuple[int, str]:
    output = io.StringIO()
    with patch.object(cli.os, "geteuid", return_value=0):
        with contextlib.redirect_stdout(output):
            rc = cli.main(args)
    return rc, output.getvalue()


def button_script(source: str, prop: str) -> str:
    section = source.split("          - type: custom:button-card", 1)[1]
    key = "            " + prop + ": |\n"
    part = section.split(key, 1)[1]
    end = part.split("            " + ("styles:" if prop == "label" else "label:"), 1)[0]
    return end.strip()


def chips_block(source: str) -> str:
    return source.split("          - type: custom:mushroom-chips-card", 1)[1].split(
        "        grid_options:", 1,
    )[0]


class PBSPVECLIGoldenTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.config = self.root / "agent.ini"
        self.config.write_text(
            "# retained\n[general]\ninstance_id = home\n"
            "[mqtt]\nhost = broker\nport = 1883\npassword = hidden-top-secret\n"
            "[pbs]\ndatastores = pbs-serzhan\n"
            "[telemetry]\nenabled = true\n"
            "[monitor]\npoll_seconds = 300\n",
            encoding="utf-8",
        )
        self.config.chmod(0o640)
        self.app = self.root / "app"
        self.app.mkdir()
        (self.app / "BUILD_INFO").write_text(
            "version=0.1.18\ncommit=" + "a" * 40 + "\n", encoding="utf-8",
        )

    def test_pve_source_contains_exact_common_text_tokens(self):
        for expected in (
            "UP_TO_DATE {current}", "UPDATING {current} -> {version}",
            "UPDATED {actual}", "Restarted ", "CHANGED", "UNCHANGED",
            "ERROR: ", "SYSTEM", "MQTT", "MONITORING",
        ):
            self.assertIn(expected, PVE_CLI)

    def test_pve_status_sections_alignment_live_and_no_secret_or_heavy_calls(self):
        observed = (datetime.now(timezone.utc) - timedelta(seconds=9)).isoformat()
        last_connected = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        (self.root / "runtime.json").write_text(json.dumps({
            "pid": 4321, "observed_at": observed, "status": "HEALTHY",
            "mqtt_last_ack": observed, "mqtt_publish_state": True,
            "pbs_version": "4.2.10",
            "datastores": [{"name": "pbs-serzhan", "used_percent": 13.1, "health": "HEALTHY"}],
            "summary": {"backup_groups": 9, "maintenance_jobs": 3},
            "pbs_errors": [],
        }))
        (self.root / "mqtt.json").write_text(json.dumps({
            "status": "CONNECTED", "reason": None, "last_connected": last_connected,
        }))
        (self.root / "control.json").write_text(json.dumps({
            "latest_version": "0.1.19", "checked_at": observed,
            "card": {"operation": None, "state": "idle"},
        }))
        (self.root / "auto_update.json").write_text('{"enabled":true}')
        (self.root / "telemetry.json").write_text(json.dumps({"last_success_epoch": 1795300000}))
        active = {
            "ActiveState": "active", "SubState": "running", "MainPID": "4321",
            "ActiveEnterTimestampMonotonic": str(int((time.monotonic() - 62) * 1000000)),
        }
        output = io.StringIO()
        with patch.object(cli, "service_info", return_value=active), \
             patch.object(cli, "host_ip", return_value="192.0.2.23"), \
             patch("socket.gethostname", return_value="mediaserver"), \
             patch.object(cli, "_read_version", return_value="0.1.18"), \
             patch.object(cli.subprocess, "run", side_effect=AssertionError("no live probes")), \
             contextlib.redirect_stdout(output):
            self.assertEqual(cli.status(self.config, self.root, self.app), 0)
        result = output.getvalue()
        self.assertTrue(result.startswith(
            "DigitalHouses PBS Agent 0.1.18 | commit " + "a" * 40 + "\nSYSTEM\n"
        ))
        for expected in (
            "\nSYSTEM\n", "\nMQTT\n", "\nPBS\n", "\nMONITORING\n",
            "\nUPDATES\n", "\nTELEMETRY\n",
            "  Service:   active/running | uptime ",
            "  Hostname:  mediaserver\n", "  IP:        192.0.2.23\n",
            "  Broker:    broker:1883\n",
            "  State:     CONNECTED | retry 60s, connect timeout 5s\n",
            "  Connected: " + last_connected,
            "  PUBACK:    " + observed,
            "  Publish:   ACKNOWLEDGED",
            "  Status:    HEALTHY", "  Version:   4.2.10",
            "  Datastore: pbs-serzhan | HEALTHY | used 13.1%",
            "  Data:      LIVE, ",
            "  Groups:    9", "  Auto:      ON",
        ):
            self.assertIn(expected, result)
        self.assertNotIn("hidden-top-secret", result)
        self.assertNotIn("{'", result)

    def test_stale_stopped_snapshots_do_not_look_live(self):
        (self.root / "runtime.json").write_text(json.dumps({
            "pid": 1234, "observed_at": datetime.now(timezone.utc).isoformat(),
            "status": "HEALTHY", "mqtt_publish_state": True,
        }))
        (self.root / "mqtt.json").write_text('{"status":"CONNECTED"}')
        output = io.StringIO()
        with patch.object(cli, "service_info", return_value={
            "ActiveState": "inactive", "SubState": "dead", "MainPID": "0",
        }), patch.object(cli, "host_ip", return_value=None), \
             patch.object(cli, "_read_version", return_value="0.1.18"), \
             contextlib.redirect_stdout(output):
            cli.status(self.config, self.root, self.app)
        value = output.getvalue()
        self.assertIn("  Service:   inactive/dead | uptime unknown", value)
        self.assertIn("  State:     UNKNOWN", value)
        self.assertIn("  Status:    STALE/UNAVAILABLE", value)
        self.assertIn("  Data:      STALE/UNAVAILABLE", value)
        self.assertNotIn("  Status:    HEALTHY", value)
        self.assertNotIn("  Publish:   ACKNOWLEDGED", value)

    def test_update_up_to_date_exact_pve_wording_without_install(self):
        with patch.object(cli, "_service_state", return_value="active"), \
             patch("app.releases.latest_release", return_value=(
                 "digitalhouses_pbs_agent-v0.1.18", "0.1.18",
             )), patch.object(cli, "_read_version", return_value="0.1.18"), \
             patch.object(cli.subprocess, "run", side_effect=AssertionError("no installer")):
            rc, output = run_main(["update"])
        self.assertEqual(rc, 0)
        self.assertEqual(output, "UP_TO_DATE 0.1.18\n")

    def test_update_announces_from_to_before_install_and_verified_version_after(self):
        data = {"installed": "0.1.18"}
        output = io.StringIO()

        def fake_installer(command, **kwargs):
            self.assertEqual(command, [
                "bash", str(cli.APP / "install.sh"), "--non-interactive",
            ])
            self.assertIn("UPDATING 0.1.18 -> 0.1.19\n", output.getvalue())
            self.assertEqual(kwargs["env"]["DIGITALHOUSES_SOURCE_REF"],
                             "digitalhouses_pbs_agent-v0.1.19")
            self.assertTrue(kwargs["capture_output"])
            self.assertTrue(kwargs["text"])
            data["installed"] = "0.1.19"
            return SimpleNamespace(
                returncode=0,
                stdout="INSTALLED digitalhouses_pbs_agent 0.1.19\nSERVICE ACTIVE\n",
                stderr="installer log is not a PVE CLI status\n",
            )

        with patch.object(cli, "_service_state", return_value="active"), \
             patch("app.releases.latest_release", return_value=(
                 "digitalhouses_pbs_agent-v0.1.19", "0.1.19",
             )), patch.object(cli, "_read_version", side_effect=lambda: data["installed"]), \
             patch.object(cli.subprocess, "run", side_effect=fake_installer), \
             patch.object(cli.os, "geteuid", return_value=0), \
             contextlib.redirect_stdout(output):
            code = cli.main(["update"])
        self.assertEqual(code, 0)
        self.assertEqual(output.getvalue(),
                         "UPDATING 0.1.18 -> 0.1.19\nUPDATED 0.1.19\n")
        self.assertNotIn("digitalhouses_pbs_agent-v", output.getvalue())

    def test_update_failure_or_version_mismatch_cannot_print_updated(self):
        from app import releases
        for case in ("failure", "mismatch"):
            with self.subTest(case=case):
                data = {"installed": "0.1.18"}
                result = SimpleNamespace(returncode=1 if case == "failure" else 0)
                out = io.StringIO()
                with patch.object(cli, "_service_state", return_value="active"), \
                     patch.object(releases, "latest_release", return_value=(
                         "digitalhouses_pbs_agent-v0.1.19", "0.1.19",
                     )), patch.object(cli, "_read_version", side_effect=lambda: data["installed"]), \
                     patch.object(cli.subprocess, "run", return_value=result), \
                     patch.object(cli.os, "geteuid", return_value=0), \
                     contextlib.redirect_stdout(out):
                    code = cli.main(["update"])
                self.assertEqual(code, 1)
                self.assertIn("UPDATING 0.1.18 -> 0.1.19", out.getvalue())
                self.assertIn("ERROR: ", out.getvalue())
                self.assertNotIn("UPDATED ", out.getvalue())

    def test_update_or_restart_inactive_requires_running_agent(self):
        with patch.object(cli, "_service_state", return_value="inactive"), \
             patch.object(cli.subprocess, "run", side_effect=AssertionError("no install")):
            for command in ("update", "restart"):
                code, output = run_main([command])
                self.assertEqual(code, 1)
                self.assertTrue(output.startswith("ERROR: "))
                self.assertNotIn("UPDATED", output)
                self.assertNotIn("Restarted ", output)

    def test_restart_exact_pve_success_and_failure_messages(self):
        with patch.object(cli, "_service_state", return_value="active"), \
             patch.object(cli.subprocess, "run",
                          return_value=SimpleNamespace(returncode=0)) as restart:
            code, output = run_main(["restart"])
        self.assertEqual(code, 0)
        self.assertEqual(output, "Restarted digitalhouses_pbs_agent.service\n")
        self.assertEqual(restart.call_args.args[0],
                         ["systemctl", "restart", "digitalhouses_pbs_agent.service"])

        with patch.object(cli, "_service_state", return_value="active"), \
             patch.object(cli.subprocess, "run",
                          return_value=SimpleNamespace(returncode=1)):
            code, output = run_main(["restart"])
        self.assertEqual(code, 1)
        self.assertIn("ERROR: systemctl restart failed", output)
        self.assertNotIn("Restarted ", output)

    def test_set_rollback_on_systemd_failure_matches_pve_transaction(self):
        original = self.config.read_bytes()
        mode = stat.S_IMODE(self.config.stat().st_mode)
        with patch.object(cli, "_service_state", return_value="active"), \
             patch.object(cli.subprocess, "run",
                          return_value=SimpleNamespace(returncode=1)):
            with self.assertRaisesRegex(RuntimeError, "rolled back"):
                cli.change_config(self.config, ["mqtt_port=1884"])
        self.assertEqual(original, self.config.read_bytes())
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), mode)

    def test_set_unchanged_does_not_restart_and_secret_never_exposed(self):
        with patch.object(cli.subprocess, "run",
                          side_effect=AssertionError("no restart")):
            self.assertEqual(cli.change_config(self.config, ["mqtt_port=1883"]),
                             "UNCHANGED")
        with patch.object(cli, "DEFAULT_CONFIG", self.config):
            code, output = run_main(["set", "mqtt_password=supersecrettext"])
        self.assertEqual(code, 1)
        self.assertIn("ERROR:", output)
        self.assertNotIn("supersecrettext", output)
        self.assertNotIn("ValueError", output)

    def test_hidden_password_prompt_and_stdin_eof_follow_pve_safety(self):
        import getpass
        class FakeTTY(io.StringIO):
            def isatty(self):
                return True
        class FakeInput(io.StringIO):
            def isatty(self):
                return False
        with patch("sys.stdin", FakeTTY()), patch.object(
            cli.getpass, "getpass", return_value="new-secret"
        ) as prompt:
            with patch.object(cli, "_service_state", return_value="inactive"):
                self.assertEqual(cli.change_config(
                    self.config, ["mqtt_password"]), "CHANGED")
        prompt.assert_called_once_with("Password: ")
        self.assertNotIn("new-secret", self.config.read_text().split("password =", 1)[0])
        with patch("sys.stdin", FakeInput("")):
            with self.assertRaisesRegex(cli.CliError, "stdin is empty"):
                cli.change_config(self.config, ["mqtt_password=-"])
        with patch("sys.stdin", FakeTTY()), patch.object(
            cli.getpass, "getpass",
            side_effect=getpass.GetPassWarning("may echo insecurely"),
        ):
            with self.assertRaisesRegex(cli.CliError, "hidden password entry unavailable"):
                cli.change_config(self.config, ["mqtt_password"])

    def test_auto_update_idempotent_exact_pve_messages(self):
        with patch.object(cli, "STATE_DIR", self.root):
            for command, text in (
                ("status", "OFF\n"), ("on", "CHANGED ON\n"),
                ("on", "UNCHANGED ON\n"), ("status", "ON\n"),
                ("off", "CHANGED OFF\n"), ("off", "UNCHANGED OFF\n"),
            ):
                code, output = run_main(["auto-update", command])
                self.assertEqual(code, 0)
                self.assertEqual(output, text)

    def test_help_usage_mapping_and_unknown_command_errors(self):
        code, output = run_main(["help"])
        self.assertEqual(code, 0)
        self.assertTrue(output.startswith(
            "Usage: /usr/local/bin/dh-pbs-agent status | update | "
            "auto-update on|off|status | restart | help | set key=value [key=value ...]\n"
        ))
        self.assertIn("Run status/update/restart/set as root or through sudo.", output)
        self.assertIn("Keys (native INI mapping):", output)
        self.assertIn("  mqtt_host: [mqtt] host", output)
        self.assertIn("check-update | telemetry-delete", output)
        self.assertIn("Full reference: ", output)
        self.assertNotIn("supersecrettext", output)
        code, output = run_main(["unknown-command"])
        self.assertEqual(code, 1)
        self.assertEqual(output, "ERROR: unknown command or arguments; use help\n")
        code, output = run_main(["set"])
        self.assertEqual(code, 1)
        self.assertTrue(output.startswith("ERROR: set requires key=value arguments"))


class PBSPVEHAGoldenTests(unittest.TestCase):
    def test_operation_label_script_is_verbatim_pve_with_entity_rename_only(self):
        pbs = PBS_VIEW_PATH.read_text(encoding="utf-8")
        expected = button_script(PVE_VIEW, "label").replace(
            "dh_pve_agent", "dh_pbs_agent",
        )
        actual = button_script(pbs, "label")
        self.assertEqual(actual, expected)

    def test_identical_operational_chip_text_order_and_ids(self):
        pbs = PBS_VIEW_PATH.read_text(encoding="utf-8")
        pve = chips_block(PVE_VIEW)
        applied = chips_block(pbs)
        names = re.findall(
            r"^\s+content: (Обновить|Версия|Новая версия|Перезапуск)\s*$",
            applied, re.MULTILINE,
        )
        original = re.findall(
            r"^\s+content: (Обновить|Версия|Новая версия|Перезапуск)\s*$",
            pve, re.MULTILINE,
        )
        self.assertEqual(names, ["Обновить", "Версия", "Новая версия", "Перезапуск"])
        self.assertEqual(names, original)
        self.assertEqual(applied.count("perform_action: button.press"), 4)
        for command in ("refresh", "check_updates", "update", "restart_agent"):
            self.assertIn(f"button.dh_pbs_agent_{command}", applied)
        self.assertEqual(applied.count("confirmation:"), 2)

    def test_original_pbs_four_section_layout_and_product_identity_unchanged(self):
        source = PBS_VIEW_PATH.read_text(encoding="utf-8")
        self.assertEqual(source.count("\n  - type: grid\n"), 4)
        self.assertIn("path: dh_pbs_agent", source)
        self.assertIn("heading: Занято на диске PBS · 30 дней", source)
        self.assertIn("'type': 'statistics-graph'", source)
        self.assertIn("'chart_type': 'bar'", source)
        self.assertIn("'period': 'day'", source)
        self.assertIn("'days_to_show': 30", source)
        self.assertIn("card_param: cards", source)
        self.assertIn("mdi:backup-restore", source)
        self.assertIn("Установить новую версию PBS Agent?", source)
        self.assertIn("Сам сервер PBS и задания резервного копирования", source)


if __name__ == "__main__":
    unittest.main()
