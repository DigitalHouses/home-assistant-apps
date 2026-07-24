from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

APP_DIR = Path(__file__).resolve().parents[1] / "rootfs" / "app"
sys.path.insert(0, str(APP_DIR))


class FakePublishInfo:
    rc = 0


class FakeClient:
    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs
        self.published: list[tuple[str, str, int, bool]] = []
        self.subscriptions: list[tuple[str, int]] = []
        self.on_connect = None
        self.on_disconnect = None
        self.on_message = None

    def username_pw_set(self, username: str, password: str) -> None:
        del username, password

    def will_set(self, *args, **kwargs) -> None:
        del args, kwargs

    def reconnect_delay_set(self, *args, **kwargs) -> None:
        del args, kwargs

    def connect_async(self, *args, **kwargs) -> None:
        del args, kwargs

    def subscribe(self, topic: str, qos: int = 0) -> None:
        self.subscriptions.append((topic, qos))

    def publish(
        self,
        topic: str,
        payload: str,
        qos: int = 0,
        retain: bool = False,
    ) -> FakePublishInfo:
        self.published.append((topic, payload, qos, retain))
        return FakePublishInfo()

    def loop_start(self) -> None:
        return None

    def loop_stop(self) -> None:
        return None

    def disconnect(self) -> None:
        return None


fake_client_module = types.ModuleType("paho.mqtt.client")
fake_client_module.Client = FakeClient
fake_client_module.MQTTMessage = object
fake_client_module.MQTT_ERR_SUCCESS = 0
fake_mqtt_package = types.ModuleType("paho.mqtt")
fake_mqtt_package.client = fake_client_module
fake_paho_package = types.ModuleType("paho")
fake_paho_package.mqtt = fake_mqtt_package
sys.modules.setdefault("paho", fake_paho_package)
sys.modules.setdefault("paho.mqtt", fake_mqtt_package)
sys.modules.setdefault("paho.mqtt.client", fake_client_module)

spec = importlib.util.spec_from_file_location("speedtest_runtime", APP_DIR / "app.py")
if spec is None or spec.loader is None:  # pragma: no cover
    raise RuntimeError("Unable to load app.py")
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)

from core import (  # noqa: E402
    append_recent_result,
    build_recent_record,
    default_recent_results,
    default_state,
)


def state_with_result(
    *,
    download: float = 34,
    upload: float = 40,
    ping: float = 20,
    timestamp: str = "2099-07-24T07:00:00Z",
) -> dict:
    state = default_state()
    state.update(
        {
            "status": "Success",
            "download_mbps": download,
            "upload_mbps": upload,
            "ping_ms": ping,
            "jitter_ms": 1.0,
            "packet_loss": None,
            "provider": "Example ISP",
            "external_ip": "203.0.113.10",
            "server": "OBIT — Almaty, Kazakhstan",
            "server_id": "56519",
            "result_url": "https://www.speedtest.net/result/c/runtime-example",
            "last_success": timestamp,
            "last_attempt": timestamp,
            "error": None,
        }
    )
    return state


class RuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        data = Path(self.temp.name)
        self.constant_patchers = []
        for name, filename in (
            ("DATA_DIR", ""),
            ("OPTIONS_FILE", "options.json"),
            ("STATE_FILE", "state.json"),
            ("SERVERS_FILE", "servers.json"),
            ("THRESHOLDS_FILE", "thresholds.json"),
            ("RECENT_RESULTS_FILE", "recent_results.json"),
            ("SCHEDULE_FILE", "schedule.json"),
        ):
            value = data if not filename else data / filename
            patcher = patch.object(runtime, name, value)
            patcher.start()
            self.constant_patchers.append(patcher)

        self.env_patcher = patch.dict(
            os.environ,
            {
                "MQTT_HOST": "mqtt",
                "MQTT_PORT": "1883",
                "MQTT_USER": "user",
                "MQTT_PASSWORD": "password",
            },
            clear=False,
        )
        self.env_patcher.start()
        self.app = runtime.SpeedtestApp()
        self.app.connected_event.set()

    def tearDown(self) -> None:
        self.env_patcher.stop()
        for patcher in reversed(self.constant_patchers):
            patcher.stop()
        self.temp.cleanup()

    def published_json(self, topic: str) -> dict:
        messages = [
            payload
            for published_topic, payload, _, _ in self.app.mqtt.published
            if published_topic == topic
        ]
        self.assertTrue(messages, f"No MQTT payload published to {topic}")
        return json.loads(messages[-1])

    def test_threshold_command_recalculates_immediately(self) -> None:
        self.app.state = state_with_result(download=34)
        self.app.thresholds["minimum_download_mbps"] = 30
        self.app.publish_evaluation(force_availability=True)
        self.assertEqual(
            self.published_json(runtime.PROBLEMS_TOPIC)["low_download"]["state"],
            "OFF",
        )

        self.app.handle_threshold_command(
            runtime.MINIMUM_DOWNLOAD_COMMAND_TOPIC,
            b"50",
        )
        payload = self.published_json(runtime.PROBLEMS_TOPIC)
        self.assertEqual(payload["low_download"]["state"], "ON")
        self.assertEqual(
            payload["low_download"]["attributes"]["current_value"],
            34,
        )
        self.assertEqual(
            payload["low_download"]["attributes"]["threshold"],
            50,
        )

    def test_threshold_command_does_not_rewrite_recent_history(self) -> None:
        state = state_with_result(download=15)
        record = build_recent_record(
            state,
            {
                "minimum_download_mbps": 10,
                "minimum_upload_mbps": 10,
                "maximum_ping_ms": 200,
            },
        )
        self.app.recent_results = append_recent_result(
            default_recent_results(),
            record,
            20,
            updated_at="2099-07-24T07:01:00Z",
        )
        original = json.loads(json.dumps(self.app.recent_results))
        self.app.state = state

        self.app.handle_threshold_command(
            runtime.MINIMUM_DOWNLOAD_COMMAND_TOPIC,
            b"20",
        )
        self.assertEqual(self.app.recent_results, original)
        self.assertEqual(
            self.app.recent_results["results"][0]["minimum_download_mbps"],
            10,
        )

    def test_thresholds_persist_across_restart(self) -> None:
        self.app.handle_threshold_command(
            runtime.MINIMUM_DOWNLOAD_COMMAND_TOPIC,
            b"55",
        )
        restarted = runtime.SpeedtestApp()
        self.assertEqual(restarted.thresholds["minimum_download_mbps"], 55)

    def test_periodic_interval_starts_from_app_option(self) -> None:
        self.assertEqual(
            self.app.schedule["periodic_test_interval_minutes"],
            30,
        )

    def test_periodic_interval_command_persists_and_signals_reschedule(self) -> None:
        self.assertFalse(self.app.periodic_schedule_changed.is_set())
        self.app.handle_periodic_interval_command(b"45")

        self.assertEqual(
            self.app.schedule["periodic_test_interval_minutes"],
            45,
        )
        self.assertTrue(self.app.periodic_schedule_changed.is_set())
        self.assertEqual(
            self.published_json(runtime.SCHEDULE_TOPIC)[
                "periodic_test_interval_minutes"
            ],
            45,
        )

        restarted = runtime.SpeedtestApp()
        self.assertEqual(
            restarted.schedule["periodic_test_interval_minutes"],
            45,
        )

    def test_invalid_periodic_interval_is_rejected(self) -> None:
        self.app.handle_periodic_interval_command(b"4")
        self.assertEqual(
            self.app.schedule["periodic_test_interval_minutes"],
            30,
        )
        self.app.handle_periodic_interval_command(b"15.5")
        self.assertEqual(
            self.app.schedule["periodic_test_interval_minutes"],
            30,
        )

    def test_changed_app_option_overrides_persisted_number_on_restart(self) -> None:
        self.app.handle_periodic_interval_command(b"45")
        runtime.atomic_write_json(
            runtime.OPTIONS_FILE,
            {"periodic_test_interval_minutes": 60},
        )

        restarted = runtime.SpeedtestApp()
        self.assertEqual(
            restarted.schedule["periodic_test_interval_minutes"],
            60,
        )

    def test_periodic_loop_restarts_countdown_after_interval_change(self) -> None:
        app = self.app

        class ScheduleEvent:
            def __init__(self) -> None:
                self.calls = 0

            def wait(self, timeout: float) -> bool:
                del timeout
                self.calls += 1
                if self.calls == 1:
                    with app.schedule_lock:
                        app.schedule["periodic_test_interval_minutes"] = 45
                    return True
                app.stop_event.set()
                return False

            def clear(self) -> None:
                return None

            def set(self) -> None:
                return None

        app.periodic_schedule_changed = ScheduleEvent()
        with self.assertLogs("digitalhouses_speedtest", level="INFO") as logs:
            app.periodic_loop()

        self.assertTrue(
            any(
                "rescheduled for 45 minutes" in message
                for message in logs.output
            )
        )

    def test_recent_results_persist_across_restart(self) -> None:
        record = build_recent_record(
            state_with_result(),
            self.app.thresholds,
        )
        self.app.recent_results = append_recent_result(
            self.app.recent_results,
            record,
            20,
            updated_at="2099-07-24T07:01:00Z",
        )
        runtime.atomic_write_json(
            runtime.RECENT_RESULTS_FILE,
            self.app.recent_results,
        )
        restarted = runtime.SpeedtestApp()
        self.assertEqual(len(restarted.recent_results["results"]), 1)
        self.assertEqual(
            restarted.recent_results["results"][0]["server_id"],
            56519,
        )

    def test_no_connectivity_preserves_measurement_and_adds_no_history(self) -> None:
        self.app.state = state_with_result(download=7)
        with patch.object(
            self.app,
            "check_connectivity_once",
            return_value={
                "google_dns": False,
                "cloudflare_dns": False,
                "checked_at": "2099-07-24T08:00:00Z",
            },
        ):
            self.app.run_speedtest()

        self.assertEqual(self.app.state["status"], "No connectivity")
        self.assertEqual(self.app.state["download_mbps"], 7)
        self.assertEqual(self.app.recent_results["results"], [])

    def test_failed_test_preserves_measurement_and_adds_no_history(self) -> None:
        self.app.state = state_with_result(download=7)
        with (
            patch.object(
                self.app,
                "check_connectivity_once",
                return_value={
                    "google_dns": True,
                    "cloudflare_dns": False,
                    "checked_at": "2099-07-24T08:00:00Z",
                },
            ),
            patch.object(
                self.app,
                "run_speedtest_candidate",
                side_effect=RuntimeError("Ookla failed"),
            ),
        ):
            self.app.run_speedtest()

        self.assertEqual(self.app.state["status"], "Error")
        self.assertEqual(self.app.state["download_mbps"], 7)
        self.assertEqual(self.app.recent_results["results"], [])

    def test_expired_result_publishes_offline_availability(self) -> None:
        self.app.state = state_with_result(timestamp="2020-01-01T00:00:00Z")
        self.app.publish_evaluation(force_availability=True)
        messages = [
            payload
            for topic, payload, _, _ in self.app.mqtt.published
            if topic == runtime.RESULT_AVAILABILITY_TOPIC
        ]
        self.assertEqual(messages[-1], "offline")

    def test_incomplete_result_is_not_available_even_with_timestamp(self) -> None:
        self.app.state = state_with_result()
        self.app.state["download_mbps"] = None
        self.assertFalse(self.app.current_result_is_available())
        self.app.publish_evaluation(force_availability=True)
        messages = [
            payload
            for topic, payload, _, _ in self.app.mqtt.published
            if topic == runtime.RESULT_AVAILABILITY_TOPIC
        ]
        self.assertEqual(messages[-1], "offline")


if __name__ == "__main__":
    unittest.main()
