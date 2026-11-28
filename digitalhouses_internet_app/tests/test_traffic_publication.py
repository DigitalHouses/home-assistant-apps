"""Traffic publication cadence regression tests."""
from datetime import datetime, timedelta, timezone
import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from test_consent import internet_app
from traffic import GIB, TrafficPublication, default_traffic_state, update_traffic


class TrafficPublicationTests(unittest.TestCase):
    def setUp(self):
        self.state = default_traffic_state("sensor.down", "sensor.up")
        self.when = datetime(2026, 11, 28, tzinfo=timezone.utc)
        self.snapshot = TrafficPublication()
        self.router = {"wan_status": "on", "download_rate_mbps": 1}
        update_traffic(self.state, GIB, GIB, when=self.when)

    def sample(self, seconds, *, available=True):
        return self.snapshot.payload(
            self.state, self.router, available=available,
            when=self.when + timedelta(seconds=seconds), monotonic=seconds,
        )

    def test_minute_accounting_and_15_minute_snapshot(self):
        initial = self.sample(0)
        for minute in range(1, 15):
            update_traffic(self.state, (minute + 1) * GIB, (minute + 1) * GIB,
                           when=self.when + timedelta(minutes=minute))
            self.router["download_rate_mbps"] = minute
            current = self.sample(minute * 60)
            for key in ("download_total_gib", "upload_total_gib",
                        "download_month_gib", "upload_month_gib", "history", "updated_at"):
                self.assertEqual(current[key], initial[key])
            self.assertEqual(current["router"]["download_rate_mbps"], minute)
        self.assertEqual(self.state["total"]["download_bytes"], 14 * GIB)
        update_traffic(self.state, 16 * GIB, 16 * GIB,
                       when=self.when + timedelta(minutes=15))
        current = self.sample(900)
        self.assertEqual(current["download_total_gib"], 15)
        self.assertEqual(current["upload_month_gib"], 15)

    def test_initial_unavailable_then_valid_sample(self):
        self.sample(0, available=False)
        update_traffic(self.state, 2 * GIB, 2 * GIB, when=self.when + timedelta(seconds=60))
        self.assertEqual(self.sample(60)["download_total_gib"], 1)

    def test_unavailability_does_not_reset_cadence(self):
        self.sample(0)
        self.sample(60, available=False)
        update_traffic(self.state, 2 * GIB, 2 * GIB, when=self.when + timedelta(seconds=120))
        self.assertEqual(self.sample(120)["download_total_gib"], 0)
        self.assertEqual(self.sample(900)["download_total_gib"], 1)

    def test_month_boundary_immediate_and_new_cadence(self):
        self.when = datetime(2026, 11, 30, 23, 59, tzinfo=timezone.utc)
        self.sample(0)
        update_traffic(self.state, 2 * GIB, 2 * GIB, when=self.when + timedelta(seconds=60))
        month = self.sample(60)
        self.assertEqual(month["month"], "2026-12")
        self.assertEqual(month["download_month_gib"], 0)
        update_traffic(self.state, 3 * GIB, 3 * GIB, when=self.when + timedelta(seconds=120))
        self.assertEqual(self.sample(900)["download_month_gib"], 0)
        self.assertEqual(self.sample(960)["download_month_gib"], 1)

    def test_runtime_deduplicates_and_republishes_cached_snapshot(self):
        app = internet_app.InternetApp.__new__(internet_app.InternetApp)
        app.lock = threading.RLock()
        app.traffic = self.state
        app.traffic_available = True
        app.config = SimpleNamespace(traffic=SimpleNamespace(configured=True))
        app.traffic_publication = self.snapshot
        app.router_telemetry = self.router
        app._last_traffic_wire = None
        app.mqtt = Mock()
        app.mqtt.is_connected.return_value = True
        app.mqtt.publish.return_value = SimpleNamespace(rc=0)
        with patch("traffic.now_local", return_value=self.when), patch("traffic.time.monotonic", return_value=0):
            app._publish_traffic()
            first = json.loads(app.mqtt.publish.call_args.args[1])
            update_traffic(self.state, 2 * GIB, 2 * GIB, when=self.when)
            app._publish_traffic()
            self.assertEqual(app.mqtt.publish.call_count, 2)
            app._publish_traffic(force=True)
            self.assertEqual(json.loads(app.mqtt.publish.call_args.args[1]), first)
            self.router["wan_status"] = "off"
            app._publish_traffic()
            current = json.loads(app.mqtt.publish.call_args.args[1])
            self.assertEqual(current["router"]["wan_status"], "off")
            self.assertEqual(current["download_total_gib"], first["download_total_gib"])
            app.traffic_available = False
            app._publish_traffic()
            self.assertEqual(app.mqtt.publish.call_args_list[-2].args[1], "offline")

    def test_mqtt_failure_retries(self):
        app = internet_app.InternetApp.__new__(internet_app.InternetApp)
        app.lock = threading.RLock()
        app.traffic = self.state
        app.traffic_available = True
        app.config = SimpleNamespace(traffic=SimpleNamespace(configured=True))
        app.traffic_publication = self.snapshot
        app.router_telemetry = self.router
        app._last_traffic_wire = None
        app.mqtt = Mock()
        app.mqtt.is_connected.return_value = True
        app.mqtt.publish.return_value = SimpleNamespace(rc=1)
        app._publish_traffic()
        self.assertIsNone(app._last_traffic_wire)
        app.mqtt.publish.return_value = SimpleNamespace(rc=0)
        app._publish_traffic()
        self.assertEqual(app.mqtt.publish.call_count, 4)
        self.assertIsNotNone(app._last_traffic_wire)
