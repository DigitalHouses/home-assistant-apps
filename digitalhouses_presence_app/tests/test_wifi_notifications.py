"""Wi-Fi link notifications: debounced network reachability and unknown failures."""
import unittest
from datetime import datetime, timedelta, timezone

from dh_presence.core import Engine, Mode, Status
from dh_presence.wifi import WifiEvidence, poll_registered_wifi
from dh_presence.discovery import discovery

NOW = datetime(2026, 10, 15, 11, 0, tzinfo=timezone.utc)
PHONE = {"user_id": "ha-user", "user_name": "Serzhan",
         "device_name": "13ProMAX .SKY",
         "tracker": "device_tracker.13promax_sky",
         "ip": "192.168.11.54", "mac": "88:b9:45:80:a7:55"}


def sample(positive):
    return lambda _: WifiEvidence(
        positive, "mac_verified" if positive else "no_reply",
        "enp6s18" if positive else None
    )


class LinkEventTests(unittest.TestCase):
    def engine(self):
        e = Engine(mode=Mode.GPS, wifi_absence_minutes=15)
        e.add(PHONE["tracker"], PHONE["device_name"], user_name="Serzhan")
        e.gps_observation(PHONE["tracker"], Status.HOME, NOW)
        return e

    def test_startup_verified_phone_is_baseline_not_fake_connection(self):
        e = self.engine()
        first = poll_registered_wifi(e, [PHONE], NOW, sample(True))
        self.assertFalse([x for x in first if x["event_type"] == "wifi_in"])
        self.assertEqual(e.residents[PHONE["tracker"]].wifi, Status.HOME)

    def test_wifi_link_disappearance_after_15_negative_minutes_then_reconnect(self):
        e = self.engine()
        self.assertFalse(poll_registered_wifi(e, [PHONE], NOW, sample(True)))
        events = []
        for minute in range(1, 16):
            when = NOW + timedelta(minutes=minute)
            events += poll_registered_wifi(e, [PHONE], when, sample(False))
            events += e.expire(when)
        self.assertFalse(events)
        self.assertEqual(e.residents[PHONE["tracker"]].wifi, Status.HOME)
        when = NOW + timedelta(minutes=16)
        events += poll_registered_wifi(e, [PHONE], when, sample(False))
        events += e.expire(when)
        self.assertEqual([x["event_type"] for x in events], ["wifi_out"])
        self.assertEqual(events[0]["timeout_minutes"], 15)
        self.assertEqual(e.residents[PHONE["tracker"]].wifi, Status.NOT_HOME)
        # In GPS-only mode, the network status must not override GPS.
        self.assertEqual(e.residents[PHONE["tracker"]].confirmed, Status.HOME)
        returned = poll_registered_wifi(
            e, [PHONE], when + timedelta(minutes=1), sample(True))
        self.assertEqual([x["event_type"] for x in returned], ["wifi_in"])
        self.assertEqual(poll_registered_wifi(
            e, [PHONE], when + timedelta(minutes=2), sample(True)), [])

    def test_probe_failure_never_reports_wifi_out_or_departure(self):
        e = self.engine()
        poll_registered_wifi(e, [PHONE], NOW, sample(True))
        events = poll_registered_wifi(
            e, [PHONE], NOW + timedelta(minutes=1),
            lambda _: WifiEvidence(False, "probe_error"))
        self.assertEqual(events, [])
        self.assertEqual(e.residents[PHONE["tracker"]].wifi, Status.UNAVAILABLE)

    def test_initial_unknown_is_baselined_then_first_actual_mac_is_wifi_in(self):
        e = self.engine()
        self.assertEqual(poll_registered_wifi(e, [PHONE], NOW, sample(False)), [])
        appeared = poll_registered_wifi(e, [PHONE], NOW+timedelta(minutes=1), sample(True))
        self.assertEqual([x["event_type"] for x in appeared], ["wifi_in"])

    def test_no_negative_events_when_registered_ip_changes_mac(self):
        e = self.engine()
        poll_registered_wifi(e, [PHONE], NOW, sample(True))
        events = poll_registered_wifi(e, [PHONE], NOW+timedelta(minutes=1),
                                     lambda _: WifiEvidence(False, "mac_mismatch"))
        self.assertFalse(events)
        self.assertEqual(e.residents[PHONE["tracker"]].wifi, Status.UNAVAILABLE)

    def test_discovery_exposes_native_wifi_lost_event_type(self):
        d = discovery("0.1.15", list(self.engine().residents.values()))
        self.assertIn("wifi_lost", d["components"]["event"]["event_types"])


if __name__ == "__main__":
    unittest.main()
