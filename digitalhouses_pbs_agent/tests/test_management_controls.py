"""PBS Agent PVE-compatible management behavior, without live PBS/MQTT/systemd."""
from __future__ import annotations

import json
import queue
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

from app.control import Controller
from app.mqtt import Publisher, discovery
from app.releases import latest_release, stable_version


ROOT = Path(__file__).resolve().parents[1]


class PublisherStub:
    def __init__(self):
        self.published = []

    def control(self, payload):
        self.published.append(json.loads(json.dumps(payload)))
        return True


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.transport = PublisherStub()
        self.control = Controller(self.path, self.transport)

    def test_refresh_is_real_and_manual_only(self):
        self.assertTrue(self.control.begin("refresh"))
        self.assertFalse(self.control.begin("refresh"))
        self.assertEqual(self.control.refresh["state"], "updating")
        self.control.collection_at("2026-11-22T01:00:00+00:00")
        self.assertIsNone(self.control.last_refresh)
        self.control.finish("refresh")
        self.assertEqual(self.control.refresh["state"], "idle")
        self.assertTrue(self.control.last_refresh)
        self.assertEqual(self.control.card["operation"], "refresh")
        self.assertGreaterEqual(self.control.card["duration_seconds"], 0)
        latest = Controller(self.path, PublisherStub())
        self.assertEqual(latest.last_refresh, self.control.last_refresh)

    def test_refresh_failed_publication_never_marks_success(self):
        self.assertTrue(self.control.begin("refresh"))
        self.control.finish("refresh", "Нет подтверждения MQTT PUBACK")
        self.assertEqual(self.control.refresh["state"], "error")
        self.assertIsNone(self.control.last_refresh)
        self.assertEqual(self.control.card["state"], "error")

    def test_install_needs_verified_new_version_and_uses_worker(self):
        self.assertFalse(self.control.queue_worker("install"))
        self.assertEqual(self.control.card["state"], "error")
        self.control.available = True
        with patch("app.control.subprocess.run", return_value=Mock(returncode=0)) as start:
            self.assertTrue(self.control.queue_worker("install"))
        start.assert_called_once()
        self.assertEqual(start.call_args.args[0], [
            "systemctl", "start", "--no-block", "digitalhouses_pbs_agent-control.service"
        ])
        current = self.control.request.load()
        self.assertEqual(current["action"], "install")
        self.assertFalse(self.control.queue_worker("restart"))
        self.control.worker.save({
            "request_id": current["request_id"], "state": "completed", "error": None,
            "duration_seconds": 3.1,
        })
        self.control.tick()
        self.assertEqual(self.control.card["state"], "success")
        self.assertFalse(self.control.available)
        self.assertEqual(self.control.card["duration_seconds"], 3.1)

    def test_restart_survives_agent_restart_with_worker_result(self):
        with patch("app.control.subprocess.run", return_value=Mock(returncode=0)):
            self.assertTrue(self.control.queue_worker("restart"))
        fresh = Controller(self.path, PublisherStub())
        self.assertEqual(fresh.card["state"], "running")
        self.assertEqual(fresh.card["operation"], "restart")
        current = fresh.request.load()
        fresh.worker.save({"request_id": current["request_id"],
                           "state": "completed", "error": None})
        fresh.tick()
        self.assertEqual(fresh.card["state"], "success")

    def test_failed_worker_never_reports_success(self):
        with patch("app.control.subprocess.run", return_value=Mock(returncode=1)):
            self.assertFalse(self.control.queue_worker("restart"))
        self.assertEqual(self.control.card["state"], "error")

    def test_manual_check_coalesces_running_background_check(self):
        import threading
        release_started = threading.Event()
        release_done = threading.Event()
        def fake_release():
            release_started.set()
            release_done.wait(2)
            return "digitalhouses_pbs_agent-v0.1.11", "0.1.11"
        with patch("app.control.latest_release", side_effect=fake_release):
            self.assertTrue(self.control.start_check(manual=False))
            self.assertTrue(release_started.wait(2))
            self.assertTrue(self.control.start_check(manual=True))
            self.assertEqual(self.control.card["state"], "running")
            self.assertFalse(self.control.start_check(manual=True))
            release_done.set()
            import time
            for _ in range(100):
                if not self.control._results.empty():
                    break
                time.sleep(.01)
            self.control.tick()
        self.assertEqual(self.control.card["operation"], "check")
        self.assertEqual(self.control.card["state"], "success")
        self.assertTrue(self.control.available)

    def test_auto_update_preference_same_as_pve_default_off(self):
        self.assertFalse(self.control.auto_update)
        self.assertTrue(self.control.set_auto_update(True))
        self.assertFalse(self.control.set_auto_update(True))
        self.assertTrue(self.control.preference.load()["enabled"])
        self.assertTrue(Controller(self.path, PublisherStub()).auto_update)
        self.control.preference.save({"enabled": False})
        self.control.tick()
        self.assertFalse(self.control.auto_update)

    def test_independent_runner_carries_one_request_only(self):
        import runpy
        worker_path = ROOT / "bin/digitalhouses-pbs-agent-control-runner"
        runner = runpy.run_path(str(worker_path), run_name="pbs_worker_test")
        main = runner["main"]
        main.__globals__["ROOT"] = self.path
        self.control.request.save({"request_id": "test-id", "action": "restart"})
        self.control.worker.save({"request_id": "test-id", "state": "queued"})
        with patch("subprocess.run", return_value=Mock(returncode=0)) as run:
            self.assertEqual(main(), 0)
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.args[0], [
                "systemctl", "restart", "digitalhouses_pbs_agent.service"
            ])
            self.assertEqual(main(), 0)
            self.assertEqual(run.call_count, 1)
        self.assertEqual(self.control.worker.load()["state"], "completed")
        self.assertIsInstance(self.control.worker.load()["duration_seconds"], (int, float))

    def test_release_selection_stable_only_and_pagination(self):
        class FakeResponse:
            def __init__(self, obj):
                self.obj = obj

            def read(self):
                return json.dumps(self.obj).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

        def opener(request, timeout):
            self.assertEqual(timeout, 12)
            return FakeResponse([
                {"tag_name": "digitalhouses_pbs_agent-v0.1.15",
                 "published_at": "2026-01-01", "draft": False, "prerelease": False},
                {"tag_name": "digitalhouses_pbs_agent-v0.1.99",
                 "published_at": "2026-01-01", "draft": False, "prerelease": True},
                {"tag_name": "digitalhouses_pve_agent-v999.0.0",
                 "published_at": "2026-01-01", "draft": False, "prerelease": False},
            ])
        self.assertEqual(latest_release(opener=opener),
                         ("digitalhouses_pbs_agent-v0.1.15", "0.1.15"))
        self.assertEqual(stable_version("0.1.15"), (0, 1, 15))

    def test_mqtt_actions_reject_retain_and_non_press(self):
        publisher = Publisher.__new__(Publisher)
        publisher.base = "DigitalHouses/Global/digitalhouses_pbs_agent/test"
        publisher.commands = queue.SimpleQueue()
        publisher.auto_update_commands = queue.SimpleQueue()
        def send(topic, payload=b"PRESS", retain=False):
            publisher._on_message(None, None, Mock(topic=publisher.base+topic,
                                                   payload=payload, retain=retain))
        send("/command/restart", retain=True)
        send("/command/auto_update", payload=b"ON", retain=True)
        send("/command/install", payload=b"OFF")
        send("/command/invalid")
        self.assertTrue(publisher.commands.empty())
        send("/command/restart")
        send("/command/check")
        self.assertEqual(publisher.commands.get_nowait(), "restart")
        self.assertEqual(publisher.commands.get_nowait(), "check")
        send("/command/auto_update", payload=b"ON")
        self.assertTrue(publisher.auto_update_commands.get_nowait())

    def test_discovery_and_yaml_header_match_pve_contract(self):
        from app.config import load_config
        source = self.path / "agent.conf"
        source.write_text("[mqtt]\nhost=broker\n[pbs]\ndatastores=backup-pool\n")
        components = discovery(load_config(source))["components"]
        for key in ("refresh", "check_updates", "update", "restart_agent"):
            self.assertEqual(components[key]["platform"], "button")
            self.assertEqual(components[key]["payload_press"], "PRESS")
            self.assertFalse(components[key]["retain"])
        for key in ("card", "latest_version", "update_status", "refresh_state", "last_refresh"):
            self.assertEqual(components[key]["platform"], "sensor")
        self.assertEqual(components["update_available"]["platform"], "binary_sensor")
        self.assertEqual(components["auto_update"]["platform"], "switch")
        self.assertFalse(components["auto_update"]["retain"])
        self.assertEqual(components["health"]["default_entity_id"], "sensor.dh_pbs_agent_health")
        self.assertEqual(components["card"]["default_entity_id"], "sensor.dh_pbs_agent_card")
        template = components["card"]["json_attributes_template"]
        self.assertIn("value_json.card.operation", template)
        self.assertIn("last_collection_at", template)
        view = (ROOT / "dashboards/ru/13_pbs.yaml").read_text()
        self.assertIn("type: custom:button-card", view)
        self.assertIn("type: custom:mushroom-chips-card", view)
        self.assertIn("sensor.dh_pbs_agent_card", view)
        self.assertIn("button.dh_pbs_agent_refresh", view)
        self.assertIn("button.dh_pbs_agent_check_updates", view)
        self.assertIn("button.dh_pbs_agent_update", view)
        self.assertIn("button.dh_pbs_agent_restart_agent", view)
        self.assertIn("text: Установить новый релиз PBS Agent?", view)
        self.assertIn("text: Перезапустить только PBS Agent?", view)
        self.assertNotIn("type: custom:auto-entities", view)

    def test_installer_one_command_and_silent_git(self):
        script = (ROOT / "install.sh").read_text()
        self.assertIn('if [[ -z "$TAG" ]]', script)
        self.assertIn('advice.detachedHead=false', script)
        self.assertIn('/usr/local/libexec/digitalhouses-pbs-agent-control-runner', script)
        self.assertIn('digitalhouses_pbs_agent-control.service', script)


if __name__ == "__main__":
    unittest.main()
