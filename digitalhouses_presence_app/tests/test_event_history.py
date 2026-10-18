"""DH Presence App owns and persists the bounded UI event history."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from app import load_options, publish_snapshot
from dh_presence.core import Engine
from dh_presence.discovery import discovery, topic
from dh_presence.history import EventHistory, DEFAULT_LIMIT, MAX_LIMIT


T = datetime(2026, 10, 18, 13, 30, tzinfo=timezone.utc)


def event(kind="zone_enter", resident="r1", **extra):
    result = {
        "event_type": kind,
        "resident_id": resident,
        "user_name": "Сержан",
        "device_name": "13ProMAX .SKY",
        "observed_at": T.isoformat(),
    }
    if kind in ("zone_enter", "zone_leave"):
        result["zone_name"] = "Office"
    result.update(extra)
    return result


class FakeMQTT:
    def __init__(self):
        self.calls = []

    def publish(self, destination, payload, **kwargs):
        self.calls.append((destination, payload))
        return True


class EventHistoryTests(unittest.TestCase):
    def test_default_config_and_invalid_bounds(self):
        with tempfile.TemporaryDirectory() as d:
            opts = {
                "presence_mode": "gps",
                "wifi_absence_minutes": 15, "gps_poll_interval_seconds": 30,
                "gps_freshness_seconds": 300, "residents": [], "exclude_users": [],
            }
            filename = Path(d) / "options.json"
            filename.write_text(json.dumps(opts))
            self.assertEqual(load_options(str(filename))["events_history_limit"], DEFAULT_LIMIT)
            for bad in (0, MAX_LIMIT + 1, True, 5.0, "5", None):
                with self.subTest(bad=bad):
                    opts["events_history_limit"] = bad
                    filename.write_text(json.dumps(opts))
                    with self.assertRaisesRegex(ValueError, "events_history_limit"):
                        load_options(str(filename))
            opts["events_history_limit"] = 8
            filename.write_text(json.dumps(opts))
            self.assertEqual(load_options(str(filename))["events_history_limit"], 8)

    def test_new_history_is_empty_and_does_not_fabricate_events(self):
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "events.json")
            history = EventHistory(path)
            self.assertEqual(history.snapshot(), {"count": 0, "limit": 5, "items": []})
            self.assertFalse(Path(path).exists())

    def test_durable_newest_first_and_limit_change(self):
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "events.json")
            history = EventHistory(path, limit=2)
            history.record(event("wifi_in"), recorded_at=T)
            history.record(event("zone_enter"), recorded_at=T + timedelta(minutes=1))
            history.record(event("zone_leave"), recorded_at=T + timedelta(minutes=2))
            snapshot = history.snapshot()
            self.assertEqual(snapshot["count"], 2)
            self.assertEqual(snapshot["limit"], 2)
            self.assertIn("Выход из зоны", snapshot["items"][0]["title"])
            self.assertEqual(snapshot["items"][0]["timestamp"],
                             (T + timedelta(minutes=2)).isoformat())
            self.assertEqual(len(EventHistory(path, 2).events), 2)
            smaller = EventHistory(path, 1)
            self.assertEqual(len(smaller.events), 1)
            self.assertEqual(len(EventHistory(path, 5).events), 1)
            self.assertEqual(smaller.snapshot()["items"][0]["details"],
                             "Сержан \\(13ProMAX \\.SKY\\) · Office")

    def test_history_uses_only_whitelisted_ui_fields(self):
        with tempfile.TemporaryDirectory() as d:
            history = EventHistory(str(Path(d) / "events.json"))
            history.record(event(user_name="A <script>alert('x')</script>",
                                 device_name="B *C*", ip="192.168.8.55",
                                 mac="aa:bb:cc:dd:ee:ff", auth_token="secret"))
            snapshot = json.dumps(history.snapshot(), ensure_ascii=False)
            stored = Path(history.path).read_text()
            for forbidden in ("192.168.8.55", "aa:bb:cc:dd:ee:ff", "auth_token", "secret"):
                self.assertNotIn(forbidden, snapshot + stored)
            self.assertIn("&lt;script&gt;", snapshot)
            self.assertIn("\\*C\\*", history.snapshot()["items"][0]["details"])

    def test_exclusion_prunes_persisted_history(self):
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "events.json")
            history = EventHistory(path)
            history.record(event("wifi_in", resident="admin"))
            history.record(event("wifi_out", resident="resident"))
            self.assertTrue(history.prune_residents({"resident"}))
            self.assertEqual(history.snapshot()["count"], 1)
            self.assertTrue(EventHistory(path).events[0]["resident_id"] == "resident")
            self.assertFalse(history.prune_residents({"resident"}))

    def test_corrupt_persistent_state_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "events.json"
            for data in ("broken", '{"schema_version":2,"events":[]}',
                         '{"schema_version":1,"events":[{}]}'):
                path.write_text(data)
                with self.assertRaises(ValueError):
                    EventHistory(str(path))

    def test_required_event_fields_and_timestamps_do_not_get_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            history = EventHistory(str(Path(d) / "events.json"))
            for invalid in (
                event(observed_at=None), event(device_name=""),
                event("zone_enter", zone_name=None), event("unknown"),
            ):
                with self.subTest(event=invalid):
                    with self.assertRaises(ValueError):
                        history.record(invalid)
            self.assertEqual(history.snapshot()["count"], 0)

    def test_single_mqtt_device_read_only_diagnostic_sensor(self):
        config = discovery("0.1.28", [], {})["components"]
        item = config["recent_events"]
        self.assertEqual(item["platform"], "sensor")
        self.assertEqual(item["default_entity_id"], "sensor.dh_presence_app_recent_events")
        self.assertEqual(item["state_topic"], topic("events/history"))
        self.assertEqual(item["json_attributes_topic"], topic("events/history"))
        self.assertNotIn("json_attributes_template", item)
        self.assertEqual(item["entity_category"], "diagnostic")

    def test_publish_snapshot_restores_history_before_broker_online(self):
        with tempfile.TemporaryDirectory() as d:
            history = EventHistory(str(Path(d) / "events.json"))
            history.record(event("wifi_in"), recorded_at=T)
            out = FakeMQTT()
            engine = Engine()
            with patch("app.publish_controls", return_value=True):
                self.assertTrue(publish_snapshot(
                    out, engine, "0.1.28", T.isoformat(), None, None, history=history))
            topics = [name for name, _ in out.calls]
            idx = topics.index(topic("events/history"))
            self.assertLess(idx, topics.index(topic("availability")))
            self.assertEqual(out.calls[idx][1]["count"], 1)


if __name__ == "__main__":
    unittest.main()
