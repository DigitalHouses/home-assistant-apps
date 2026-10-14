import unittest
from datetime import datetime, timedelta, timezone
from dh_presence.core import Engine, Mode, Status, haversine_km, resident_key

T0 = datetime(2026, 10, 14, tzinfo=timezone.utc)


class TestEngine(unittest.TestCase):
    def engine(self, mode=Mode.GPS):
        e = Engine(mode=mode)
        e.add("user-1", "Resident", "companion-1", "device_tracker.iphone")
        return e

    def test_initial_unknown(self):
        self.assertIs(self.engine().overall(), Status.UNAVAILABLE)

    def test_restore_preserves_home(self):
        e = self.engine()
        e.gps_observation("user-1", Status.HOME, T0)
        stored = e.persistent()["residents"][0]
        new = Engine()
        new.add("user-1", "Resident", "companion-1", "device_tracker.iphone", stored)
        self.assertIs(new.overall(), Status.HOME)
        new.expire(T0 + timedelta(days=10))
        self.assertIs(new.overall(), Status.HOME)

    def test_no_fake_initial_arrival(self):
        e = self.engine()
        self.assertEqual(e.gps_observation("user-1", Status.HOME, T0), [])

    def test_real_transitions(self):
        e = self.engine()
        e.gps_observation("user-1", Status.HOME, T0)
        events = e.gps_observation("user-1", Status.NOT_HOME, T0 + timedelta(minutes=1))
        self.assertEqual([x["event_type"] for x in events], ["gps_out", "departure"])

    def test_unavailable_preserves_last_known(self):
        e = self.engine()
        e.gps_observation("user-1", Status.HOME, T0)
        e.expire(T0+timedelta(hours=1))
        self.assertIs(e.overall(), Status.HOME)

    def test_wifi_no_unverified_absence(self):
        e = self.engine(Mode.HYBRID)
        e.gps_observation("user-1", Status.HOME, T0)
        with self.assertRaises(ValueError):
            e.wifi_observation("user-1", Status.NOT_HOME, T0+timedelta(seconds=1), verified=False)
        self.assertIs(e.overall(), Status.HOME)

    def test_wifi_home_corrects_gps(self):
        e = self.engine(Mode.HYBRID)
        e.gps_observation("user-1", Status.NOT_HOME, T0)
        e.wifi_observation("user-1", Status.HOME, T0+timedelta(seconds=5), verified=True)
        self.assertIs(e.overall(), Status.HOME)

    def test_arp_gaps_do_not_prove_absence(self):
        e = self.engine(Mode.HYBRID)
        e.gps_observation("user-1", Status.HOME, T0)
        e.wifi_observation("user-1", Status.NOT_HOME, T0+timedelta(minutes=1), verified=True)
        e.expire(T0+timedelta(minutes=5))
        self.assertIs(e.overall(), Status.HOME)

    def test_aggregate_unknown_if_any_not_known(self):
        e = self.engine()
        e.add("user-2", "Second", "companion-2", "device_tracker.second")
        e.gps_observation("user-1", Status.NOT_HOME, T0)
        self.assertIs(e.overall(), Status.UNAVAILABLE)

    def test_coordinates(self):
        self.assertLess(haversine_km(43.2,76.9,43.2,76.9),0.001)
        with self.assertRaises(ValueError):
            haversine_km(100,0,43,76)

    def test_keys_are_stable(self):
        self.assertEqual(resident_key("user-1"),resident_key("user-1"))
        self.assertNotEqual(resident_key("user-1"),resident_key("user-2"))
