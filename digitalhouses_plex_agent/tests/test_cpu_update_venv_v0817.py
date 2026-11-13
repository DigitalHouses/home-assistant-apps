"""v0.8.17 regression coverage: native updater, self CPU, Debian venv."""
from __future__ import annotations

import contextlib
import io
import json
import os
import threading
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
import subprocess
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from app import cli
from app.agent_process_cpu import AgentProcessCpu
from app.config import load_config
from app.discovery import build_discovery_payload, build_topics
from app.models import BuildInfo
from app.runtime_status import RuntimeStatus

ROOT = Path(__file__).resolve().parents[1]


class SelfCpuTests(TestCase):
    def test_sustained_overload_then_recovery(self):
        cpu = AgentProcessCpu()
        self.assertIsNone(cpu.observe(now=0, cpu_time=0))
        for sec in range(10, 311, 10):
            self.assertEqual(cpu.observe(now=sec, cpu_time=sec * .85), 85.0)
            self.assertEqual(cpu.overloaded, sec == 310)
        current = 310 * .85
        for sec in range(320, 441, 10):
            current += 3.0
            cpu.observe(now=sec, cpu_time=current)
            self.assertEqual(cpu.overloaded, sec < 440)

    def test_large_gap_resets_confirmation_and_multicore_can_exceed_100(self):
        cpu = AgentProcessCpu()
        cpu.observe(now=1, cpu_time=0)
        self.assertEqual(cpu.observe(now=11, cpu_time=15), 150.0)
        self.assertIsNone(cpu.observe(now=111, cpu_time=80))
        self.assertFalse(cpu.overloaded)
        self.assertIsNone(cpu.snapshot()["usage_percent"])

    def test_local_runtime_persists_latest_even_offline(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "status.json"
            writer = RuntimeStatus(p, BuildInfo("0.8.17", "release", "abcdef"))
            writer.update({"state": "MQTT_PAUSED"}, "ok", {"hostname": "vm"},
                          agent_cpu={"usage_percent": 88.1, "overloaded": True})
            result = json.loads(p.read_text())
            self.assertEqual(result["agent_process_cpu"]["overloaded"], True)
            self.assertEqual(result["mqtt"]["state"], "MQTT_PAUSED")
            self.assertNotIn("password", result)

    def test_cli_displays_live_cpu_problem_without_network(self):
        with tempfile.TemporaryDirectory() as d:
            cfg=Path(d)/"settings.ini"
            cfg.write_text("[mqtt]\nhost=192.0.2.1\n")
            status=Path(d)/"runtime.json"
            writer=RuntimeStatus(status,BuildInfo("0.8.17","release","abcd"))
            writer.update({"state":"CONNECTED"},"ok",{"hostname":"plex","ip":"192.0.2.3"},
                          agent_cpu={"usage_percent":93.2,"overloaded":True})
            # Stable synthetic boot-relative clock: CI runners can have uptime <30s.
            uptime=90.0
            service={"ActiveState":"active","SubState":"running",
                     "MainPID":str(os.getpid()),
                     "ExecMainStartTimestampMonotonic":str(int(uptime*1e6)),
                     "ActiveEnterTimestampMonotonic":str(int(uptime*1e6))}
            with patch.object(cli,"service_info",return_value=service), patch(
                "app.runtime_status.host_identity",
                return_value={"hostname":"plex","ip":"192.0.2.3"}
            ),patch.object(cli.time,"monotonic",return_value=100.0),contextlib.redirect_stdout(io.StringIO()) as output:
                cli.print_status(cfg,runtime_path=status)
            self.assertIn("Agent CPU: 93% | overload ON",output.getvalue())

    def test_discovery_uses_product_availability_not_plex_collector(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "plex.ini"
            cfg.write_text("[mqtt]\nhost=broker\n")
            config = load_config(cfg)
            topics = build_topics(config)
            components = build_discovery_payload(config, BuildInfo("0.8.17","release","abc"))["components"]
        sensor = components["agent_process_cpu_usage"]
        binary = components["agent_cpu_overload"]
        event = components["agent_cpu_diagnostic_event"]
        self.assertEqual(sensor["default_entity_id"], "sensor.dh_plex_agent_process_cpu_usage")
        self.assertEqual(sensor["state_class"], "measurement")
        self.assertEqual(sensor["unit_of_measurement"], "%")
        self.assertEqual(binary["default_entity_id"], "binary_sensor.dh_plex_agent_cpu_overload")
        self.assertEqual(binary["device_class"], "problem")
        self.assertEqual(binary["payload_on"], "ON")
        self.assertEqual(binary["payload_off"], "OFF")
        self.assertEqual(sensor["state_topic"], topics.state + "/agent/process_cpu")
        self.assertEqual(sensor["state_topic"], binary["state_topic"])
        for entity in (sensor,binary):
            self.assertEqual(entity["availability"], [{
                "topic": topics.app_availability,
                "payload_available": "online", "payload_not_available": "offline",
            }])
        self.assertEqual(event["default_entity_id"], "event.dh_plex_agent_cpu_diagnostic")
        self.assertEqual(event["state_topic"], topics.base + "/events/agent_cpu")
        self.assertEqual(event["event_types"],
                         ["agent_cpu_overload_started","agent_cpu_overload_cleared"])
        self.assertEqual(event["qos"], 1)
        self.assertEqual(components["diagnostic_event"]["default_entity_id"],
                         "event.dh_plex_agent_gpu_diagnostic")
        self.assertEqual(components["cpu"]["default_entity_id"],
                         "sensor.dh_plex_agent_cpu")

    def test_cpu_event_is_qos1_live_only_and_does_not_replace_gpu_topic(self):
        from app.mqtt_bridge import MqttBridge
        bridge=MqttBridge.__new__(MqttBridge)
        bridge.connected=threading.Event()
        bridge.topics=SimpleNamespace(cpu_diagnostic_event="plex/events/agent_cpu")
        bridge._lock=threading.RLock()
        bridge._diagnostics={}
        bridge._now=lambda: "2026-11-14T00:00:00Z"
        bridge._publish=MagicMock()
        receipt=MagicMock()
        receipt.is_published.return_value=True
        bridge._publish.return_value=receipt
        event={"event_type":"agent_cpu_overload_started","timestamp":"2026-11-14T00:00:00Z"}
        self.assertFalse(bridge.publish_cpu_diagnostic_event(event))
        bridge._publish.assert_not_called()
        bridge.connected.set()
        self.assertTrue(bridge.publish_cpu_diagnostic_event(event))
        args=bridge._publish.call_args
        self.assertEqual(args.args[0],"plex/events/agent_cpu")
        self.assertEqual(args.kwargs,{"qos":1,"retain":False})



class CliUpdateTests(TestCase):
    def paths(self, base):
        root = Path(base)
        app = root / "app"
        state = root / "state"
        updater = root / "updater"
        for directory in (app,state,updater):
            directory.mkdir()
        (app / "VERSION").write_text("0.8.16\n")
        return app, state, updater

    def test_new_release_uses_existing_transactional_systemd_updater(self):
        with tempfile.TemporaryDirectory() as d:
            app,state,updater = self.paths(d)
            def run(cmd, **kwargs):
                if cmd[:3] == ["systemctl","is-active","--quiet"]:
                    return subprocess.CompletedProcess(cmd,3)
                self.assertEqual(cmd,["systemctl","start",cli.UPDATE_SERVICE])
                (app / "VERSION").write_text("0.8.17\n")
                (updater / "update_worker.json").write_text('{"state":"completed"}')
                return subprocess.CompletedProcess(cmd,0)
            with patch.object(cli,"service_info",return_value={"ActiveState":"active"}), patch(
                "app.update_manager.latest_release",
                return_value=("digitalhouses_plex_agent-v0.8.17","0.8.17")
            ),patch.object(cli.subprocess,"run",side_effect=run), contextlib.redirect_stdout(
                io.StringIO()
            ) as output:
                cli.update_agent(app_dir=app,state_dir=state,updater_dir=updater)
            request=json.loads((state/"update_request.json").read_text())
            self.assertEqual(request["tag"],"digitalhouses_plex_agent-v0.8.17")
            self.assertEqual(request["version"],"0.8.17")
            self.assertIn("UPDATED 0.8.17",output.getvalue())

    def test_up_to_date_does_not_trigger_systemd(self):
        with tempfile.TemporaryDirectory() as d:
            app,state,updater=self.paths(d)
            with patch.object(cli,"service_info",return_value={"ActiveState":"active"}), patch(
                "app.update_manager.latest_release",
                return_value=("digitalhouses_plex_agent-v0.8.16","0.8.16")
            ),patch.object(cli.subprocess,"run") as execute, contextlib.redirect_stdout(
                io.StringIO()
            ) as output:
                cli.update_agent(app_dir=app,state_dir=state,updater_dir=updater)
            self.assertIn("UP_TO_DATE 0.8.16",output.getvalue())
            execute.assert_not_called()

    def test_busy_update_rejected_without_overwriting_request(self):
        with tempfile.TemporaryDirectory() as d:
            app,state,updater=self.paths(d)
            (state/"update_request.json").write_text('{"tag":"old"}')
            (updater/"update_worker.json").write_text('{"state":"installing"}')
            with patch.object(cli,"service_info",return_value={"ActiveState":"active"}), patch(
                "app.update_manager.latest_release",
                return_value=("digitalhouses_plex_agent-v0.8.17","0.8.17")
            ),patch.object(cli.subprocess,"run",
                           return_value=subprocess.CompletedProcess([],3)):
                with self.assertRaisesRegex(cli.CliError,"previous update"):
                    cli.update_agent(app_dir=app,state_dir=state,updater_dir=updater)
            self.assertEqual((state/"update_request.json").read_text(),'{"tag":"old"}')


class DebianVenvTests(TestCase):
    def test_prereq_detects_ensurepip_not_venv_help(self):
        source=(ROOT/"install.sh").read_text()
        block=source.split("need_apt=0",1)[1].split("if [[",1)[0]
        self.assertIn("python3 -c 'import ensurepip'",block)
        self.assertNotIn("python3 -m venv --help",block)
        self.assertIn("python3-venv",source)

    def test_half_created_venv_checked_for_pip(self):
        source=(ROOT/"install.sh").read_text()
        d=chr(36)+"{APP_DIR}"
        self.assertIn(f'"{d}/.venv/bin/python" -m pip --version',source)
        self.assertIn(f'python3 -m venv "{d}/.venv"',source)
