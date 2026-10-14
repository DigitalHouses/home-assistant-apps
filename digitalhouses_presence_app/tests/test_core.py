import unittest
from datetime import datetime, timedelta, timezone

from dh_presence.core import Engine, Mode, Status, haversine_km, resident_key

T0 = datetime(2026, 10, 14, tzinfo=timezone.utc)


class TestEngine(unittest.TestCase):
    def engine(self, mode=Mode.GPS):
        e = Engine(mode=mode)
        e.add("device_tracker.iphone", "iPhone")
        return e

    def test_initial_unknown(self):
        self.assertIs(self.engine().overall(), Status.UNAVAILABLE)

    def test_restore_preserves_home(self):
        e = self.engine()
        e.gps_observation("device_tracker.iphone", Status.HOME, T0)
        saved = e.persistent()
        self.assertEqual(saved["schema_version"], 2)
        new = Engine()
        new.add("device_tracker.iphone", "iPhone", saved["residents"][0])
        self.assertIs(new.overall(), Status.HOME)
        new.expire(T0 + timedelta(days=10))
        self.assertIs(new.overall(), Status.HOME)

    def test_no_fake_initial_arrival(self):
        e = self.engine()
        self.assertEqual(e.gps_observation("device_tracker.iphone", Status.HOME, T0), [])

    def test_real_transitions(self):
        e = self.engine()
        e.gps_observation("device_tracker.iphone", Status.HOME, T0)
        events = e.gps_observation("device_tracker.iphone", Status.NOT_HOME, T0 + timedelta(minutes=1))
        self.assertEqual([x["event_type"] for x in events], ["gps_out", "departure"])

    def test_unavailable_preserves_last_known(self):
        e = self.engine()
        e.gps_observation("device_tracker.iphone", Status.HOME, T0)
        e.expire(T0 + timedelta(hours=1))
        self.assertIs(e.overall(), Status.HOME)

    def test_wifi_no_unverified_absence(self):
        e = self.engine(Mode.HYBRID)
        e.gps_observation("device_tracker.iphone", Status.HOME, T0)
        with self.assertRaises(ValueError):
            e.wifi_observation("device_tracker.iphone", Status.NOT_HOME, T0 + timedelta(seconds=1), verified=False)
        self.assertIs(e.overall(), Status.HOME)

    def test_wifi_home_corrects_gps(self):
        e = self.engine(Mode.HYBRID)
        e.gps_observation("device_tracker.iphone", Status.NOT_HOME, T0)
        e.wifi_observation("device_tracker.iphone", Status.HOME, T0 + timedelta(seconds=5), verified=True)
        self.assertIs(e.overall(), Status.HOME)

    def test_arp_gaps_do_not_prove_absence(self):
        e = self.engine(Mode.HYBRID)
        e.gps_observation("device_tracker.iphone", Status.HOME, T0)
        e.wifi_observation("device_tracker.iphone", Status.NOT_HOME, T0 + timedelta(minutes=1), verified=True)
        e.expire(T0 + timedelta(minutes=5))
        self.assertIs(e.overall(), Status.HOME)

    def test_aggregate_unknown_if_any_not_known(self):
        e = self.engine()
        e.add("device_tracker.second", "Second")
        e.gps_observation("device_tracker.iphone", Status.NOT_HOME, T0)
        self.assertIs(e.overall(), Status.UNAVAILABLE)

    def test_coordinates(self):
        self.assertLess(haversine_km(43.2, 76.9, 43.2, 76.9), 0.001)
        with self.assertRaises(ValueError):
            haversine_km(100, 0, 43, 76)

    def test_keys_are_tracker_based(self):
        self.assertEqual(resident_key("device_tracker.iphone"), resident_key("device_tracker.iphone"))
        self.assertNotEqual(resident_key("device_tracker.iphone"), resident_key("device_tracker.ipad"))

    def test_duplicate_tracker_rejected(self):
        e = self.engine()
        with self.assertRaises(ValueError):
            e.add("device_tracker.iphone", "Again")

    def test_invalid_tracker_rejected(self):
        for name in ("person.me", "sensor.iphone", "device_tracker.", "", None):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    resident_key(name)

    def test_iPad_not_implicitly_included(self):
        e = self.engine()
        self.assertEqual(set(e.residents), {"device_tracker.iphone"})
        self.assertNotIn("device_tracker.ipad", e.residents)

    def test_switch_mode_does_not_emit_transition(self):
        e = self.engine()
        e.gps_observation("device_tracker.iphone", Status.HOME, T0)
        e.set_mode(Mode.WIFI)
        e.residents["device_tracker.iphone"].initialized = False
        self.assertEqual(e.gps_observation("device_tracker.iphone", Status.NOT_HOME, T0 + timedelta(seconds=2)), [])
        self.assertEqual(e.snapshot()["status"], "unavailable")
