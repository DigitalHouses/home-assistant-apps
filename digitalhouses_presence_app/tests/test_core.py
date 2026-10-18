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

    def test_idle_phone_for_two_days_preserves_gps_and_distance(self):
        e = self.engine()
        e.gps_observation("device_tracker.iphone", Status.HOME, T0, distance=0.13)
        e.expire(T0 + timedelta(days=2))
        resident = e.residents["device_tracker.iphone"]
        self.assertIs(e.overall(), Status.HOME)
        self.assertIs(resident.gps, Status.HOME)
        self.assertEqual(resident.distance, 0.13)
        self.assertEqual(e.snapshot()["residents"][resident.key]["gps_reported_at"], T0.isoformat())
        self.assertEqual(e.gps_observation("device_tracker.iphone", Status.HOME, T0, 0.13), [])
        self.assertIs(e.overall(), Status.HOME)
        events = e.gps_observation("device_tracker.iphone", Status.NOT_HOME, T0 + timedelta(days=2, seconds=1))
        self.assertEqual([x["event_type"] for x in events], ["gps_out", "departure"])

    def test_gps_unavailable_transition_time_is_not_previous_home_time(self):
        e = self.engine()
        tracker = "device_tracker.iphone"
        resident = e.residents[tracker]
        e.gps_observation(tracker, Status.HOME, T0, distance=0.13)
        self.assertEqual(resident.gps_changed_at, T0)
        unavailable_at = T0 + timedelta(hours=2)
        e.gps_unavailable(tracker, unavailable_at)
        self.assertIs(resident.gps, Status.UNAVAILABLE)
        self.assertEqual(resident.gps_changed_at, unavailable_at)
        self.assertIsNone(resident.distance)
        self.assertEqual(resident.last_gps_at, T0)
        # Repeated outage polling does not fabricate a new transition time.
        e.gps_unavailable(tracker, unavailable_at + timedelta(minutes=1))
        self.assertEqual(resident.gps_changed_at, unavailable_at)
        self.assertIs(e.overall(), Status.HOME)  # Durable presence is preserved.
        # A fresh trusted observation restores GPS status, without
        # synthesizing a household arrival after a mere source outage.
        restored_at = unavailable_at + timedelta(minutes=2)
        self.assertEqual(e.gps_observation(tracker, Status.HOME, restored_at), [])
        self.assertIs(resident.gps, Status.HOME)
        self.assertEqual(resident.gps_changed_at, restored_at)
        self.assertEqual(e.gps_observation(tracker, Status.HOME, restored_at), [])
        self.assertEqual(resident.gps_changed_at, restored_at)

    def test_unknown_gps_unavailable_without_prior_state_has_no_start_time(self):
        e = self.engine()
        tracker = "device_tracker.iphone"
        e.gps_unavailable(tracker, T0)
        self.assertIsNone(e.residents[tracker].gps_changed_at)
        with self.assertRaisesRegex(ValueError, "Timezone-aware"):
            e.gps_unavailable(tracker, datetime(2026, 10, 14))

    def test_idle_phone_in_hybrid_mode_does_not_become_away(self):
        e = self.engine(Mode.HYBRID)
        e.gps_observation("device_tracker.iphone", Status.HOME, T0)
        e.expire(T0 + timedelta(days=2))
        self.assertIs(e.overall(), Status.HOME)
        self.assertEqual(e.gps_observation("device_tracker.iphone", Status.HOME, T0), [])

    def test_unknown_initial_source_remains_unavailable(self):
        e = self.engine()
        e.expire(T0 + timedelta(days=2))
        self.assertIs(e.overall(), Status.UNAVAILABLE)
        self.assertIs(e.residents["device_tracker.iphone"].gps, Status.UNAVAILABLE)

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

    def test_one_negative_arp_probe_does_not_override_gps_home(self):
        e = self.engine(Mode.HYBRID)
        e.gps_observation("device_tracker.iphone", Status.HOME, T0)
        e.wifi_no_reply("device_tracker.iphone", T0 + timedelta(minutes=1))
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

    def test_user_label_does_not_change_tracker_identity_or_saved_state(self):
        e = Engine()
        e.add("device_tracker.phone", "Phone", user_name="Жилец")
        resident = e.residents["device_tracker.phone"]
        self.assertEqual(e.snapshot()["residents"][resident.key]["user_name"], "Жилец")
        self.assertEqual(resident.key, resident_key("device_tracker.phone"))
        self.assertNotIn("user_name", e.persistent()["residents"][0])
