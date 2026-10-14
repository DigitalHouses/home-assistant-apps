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

    def test_first_arrival_and_last_departure_are_strict_overall_transitions(self):
        e = Engine()
        e.add("device_tracker.one", "Phone A")
        e.add("device_tracker.two", "Phone B")
        e.gps_observation("device_tracker.one", Status.NOT_HOME, T0)
        e.gps_observation("device_tracker.two", Status.NOT_HOME, T0)
        # Initial observations do not emit synthetic arrival/departure.
        first = e.gps_observation("device_tracker.one", Status.HOME, T0 + timedelta(seconds=10))
        arrival = [x for x in first if x["event_type"] == "arrival"][0]
        self.assertTrue(arrival["first_arrival"])
        self.assertFalse(arrival["last_departure"])
        self.assertEqual(arrival["residents_home_after"], 1)
        second = e.gps_observation("device_tracker.two", Status.HOME, T0 + timedelta(seconds=11))
        arrival2 = [x for x in second if x["event_type"] == "arrival"][0]
        self.assertFalse(arrival2["first_arrival"])
        self.assertEqual(arrival2["residents_home_after"], 2)
        left_first = e.gps_observation("device_tracker.one", Status.NOT_HOME, T0 + timedelta(seconds=12))
        departure1 = [x for x in left_first if x["event_type"] == "departure"][0]
        self.assertFalse(departure1["last_departure"])
        self.assertEqual(departure1["residents_home_after"], 1)
        left_last = e.gps_observation("device_tracker.two", Status.NOT_HOME, T0 + timedelta(seconds=13))
        departure2 = [x for x in left_last if x["event_type"] == "departure"][0]
        self.assertTrue(departure2["last_departure"])
        self.assertEqual(departure2["residents_home_after"], 0)

    def test_unavailable_household_never_claims_first_or_last(self):
        e = Engine()
        e.add("device_tracker.one", "Phone A")
        e.add("device_tracker.two", "Phone B")
        e.gps_observation("device_tracker.one", Status.NOT_HOME, T0)
        e.gps_observation("device_tracker.one", Status.HOME, T0 + timedelta(seconds=1))
        first = e.gps_observation("device_tracker.one", Status.NOT_HOME, T0 + timedelta(seconds=2))
        departure = [x for x in first if x["event_type"] == "departure"][0]
        self.assertFalse(departure["last_departure"])
        self.assertFalse(departure["first_arrival"])
        self.assertIs(e.overall(), Status.UNAVAILABLE)

    def test_simultaneous_changes_have_one_first_and_one_last(self):
        e = Engine()
        e.add("device_tracker.one", "Phone A")
        e.add("device_tracker.two", "Phone B")
        for phone in e.residents:
            e.gps_observation(phone, Status.NOT_HOME, T0)
        arrivals = []
        for phone in e.residents:
            arrivals += e.gps_observation(phone, Status.HOME, T0 + timedelta(minutes=1))
        self.assertEqual(sum(x["first_arrival"] for x in arrivals if x["event_type"] == "arrival"), 1)
        departures = []
        for phone in e.residents:
            departures += e.gps_observation(phone, Status.NOT_HOME, T0 + timedelta(minutes=2))
        self.assertEqual(sum(x["last_departure"] for x in departures if x["event_type"] == "departure"), 1)
