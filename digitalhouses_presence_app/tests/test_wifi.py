"""Completed negative ARP is debounced; failed probes are never away."""
import unittest
from datetime import datetime, timedelta, timezone

from dh_presence.core import Engine, Mode, Status
from dh_presence.wifi import WifiEvidence, poll_registered_wifi, probe_registered_phone
from dh_presence.registration import ArpNoReply

T0 = datetime(2026, 10, 15, 7, 0, tzinfo=timezone.utc)
LINK = {"user_id": "ha-user", "user_name": "Resident",
        "device_name": "iPhone", "tracker": "device_tracker.phone",
        "ip": "192.168.11.54", "mac": "88:b9:45:80:a7:55"}


def engine(mode=Mode.GPS, last="home"):
    e = Engine(mode=mode, wifi_absence_minutes=15, freshness_seconds=300)
    e.add("device_tracker.phone", "iPhone", {"confirmed": last}, user_name="Resident")
    return e


class WifiEvidenceTests(unittest.TestCase):
    def test_matching_mac_returns_trusted_home(self):
        probe = lambda ip: ("88:B9:45:80:A7:55", "enp6s18")
        self.assertEqual(
            probe_registered_phone(LINK, probe),
            WifiEvidence(True, "mac_verified", "enp6s18"))

    def test_mismatch_ip_reassignment_is_not_a_new_resident(self):
        self.assertEqual(probe_registered_phone(
            LINK, lambda ip: ("02:aa:bb:cc:dd:ee", "enp6s18")),
            WifiEvidence(False, "mac_mismatch"))

    def test_no_reply_is_distinct_from_probing_failure(self):
        self.assertEqual(probe_registered_phone(
            LINK, lambda _ip: (_ for _ in ()).throw(ArpNoReply("no response"))),
            WifiEvidence(False, "no_reply"))
        for error in (RuntimeError("arp error"), TimeoutError(),
                      OSError("Network down"), ValueError("Not on link")):
            with self.subTest(error=type(error).__name__):
                def fail(_ip):
                    raise error
                self.assertEqual(probe_registered_phone(LINK, fail),
                                 WifiEvidence(False, "probe_error"))

    def test_registered_phone_only_no_router_or_nmap(self):
        e = engine()
        e.add("device_tracker.other", "Unknown")
        called = []
        def probe(record):
            called.append(record["tracker"])
            return WifiEvidence(True, "mac_verified", "enp6s18")
        events = poll_registered_wifi(e, [LINK], T0, probe)
        self.assertEqual(called, ["device_tracker.phone"])
        self.assertEqual(e.residents[LINK["tracker"]].wifi, Status.HOME)
        self.assertEqual(e.residents["device_tracker.other"].wifi, Status.UNAVAILABLE)
        self.assertFalse(any(x["event_type"] == "wifi_out" for x in events))

    def test_15_minutes_of_completed_no_reply_sets_wifi_off_but_not_hybrid_away(self):
        e = engine(Mode.HYBRID)
        e.gps_observation(LINK["tracker"], Status.HOME, T0)
        poll_registered_wifi(e, [LINK], T0,
                             lambda rec: WifiEvidence(True, "mac_verified", "enp6s18"))
        events = []
        for minute in range(1, 17):
            now = T0 + timedelta(minutes=minute)
            events += poll_registered_wifi(
                e, [LINK], now, lambda rec: WifiEvidence(False, "no_reply"))
            events += e.expire(now)
        self.assertEqual(e.residents[LINK["tracker"]].wifi, Status.NOT_HOME)
        # Legacy ARP proof can change the Wi-Fi diagnostic source, but a
        # disconnected or discharged phone must not override GPS HOME.
        self.assertEqual(e.residents[LINK["tracker"]].confirmed, Status.HOME)
        self.assertEqual([x["event_type"] for x in events], ["wifi_out"])
        self.assertEqual(e.residents[LINK["tracker"]].wifi_probe_result, "no_reply")
        self.assertEqual(e.snapshot()["residents"][e.residents[LINK["tracker"]].key]["wifi_changed_at"],
                         (T0+timedelta(minutes=16)).isoformat())

    def test_network_failure_resets_negative_streak_and_never_departs(self):
        e = engine(Mode.HYBRID)
        e.gps_observation(LINK["tracker"], Status.HOME, T0)
        poll_registered_wifi(e, [LINK], T0,
                             lambda rec: WifiEvidence(True, "mac_verified", "enp6s18"))
        for minute in range(1, 12):
            poll_registered_wifi(e, [LINK], T0+timedelta(minutes=minute),
                                 lambda rec: WifiEvidence(False, "no_reply"))
        poll_registered_wifi(e, [LINK], T0+timedelta(minutes=12),
                             lambda rec: WifiEvidence(False, "probe_error"))
        self.assertEqual(e.residents[LINK["tracker"]].wifi, Status.UNAVAILABLE)
        self.assertIsNone(e.residents[LINK["tracker"]].wifi_absent_since)
        events = []
        for minute in range(13, 18):
            now = T0+timedelta(minutes=minute)
            events += poll_registered_wifi(e, [LINK], now,
                                           lambda rec: WifiEvidence(False, "no_reply"))
            events += e.expire(now)
        self.assertFalse(any(x["event_type"] in ("wifi_out", "departure") for x in events))
        self.assertEqual(e.residents[LINK["tracker"]].confirmed, Status.HOME)

    def test_positive_reply_recovers_wifi_without_false_hybrid_arrival(self):
        e = engine(Mode.HYBRID)
        e.gps_observation(LINK["tracker"], Status.HOME, T0)
        poll_registered_wifi(e, [LINK], T0,
                             lambda rec: WifiEvidence(True, "mac_verified", "enp6s18"))
        for minute in range(1,17):
            poll_registered_wifi(e, [LINK], T0+timedelta(minutes=minute),
                                 lambda rec: WifiEvidence(False, "no_reply"))
        events = poll_registered_wifi(
            e, [LINK], T0+timedelta(minutes=17),
            lambda rec: WifiEvidence(True, "mac_verified", "enp6s18"))
        self.assertEqual(e.residents[LINK["tracker"]].confirmed, Status.HOME)
        self.assertEqual([x["event_type"] for x in events], ["wifi_in"])

    def test_wifi_only_mode_off_after_completed_negative_not_uncertainty(self):
        e = engine(Mode.WIFI, "home")
        self.assertEqual(e.snapshot()["status"], "unavailable")
        poll_registered_wifi(e, [LINK], T0,
                             lambda rec: WifiEvidence(True, "mac_verified", "enp6s18"))
        self.assertEqual(e.snapshot()["status"], "home")
        for minute in range(1,17):
            now = T0+timedelta(minutes=minute)
            poll_registered_wifi(e, [LINK], now,
                                 lambda rec: WifiEvidence(False, "no_reply"))
            e.expire(now)
        self.assertEqual(e.snapshot()["status"], "not_home")
        self.assertEqual(e.snapshot()["residents_home"], 0)

    def test_stale_gps_away_does_not_cancel_fresh_hybrid_wifi_home(self):
        e = engine(Mode.HYBRID, "not_home")
        e.gps_observation(LINK["tracker"], Status.NOT_HOME, T0-timedelta(days=1))
        poll_registered_wifi(e, [LINK], T0,
                             lambda record: WifiEvidence(True, "mac_verified", "enp6s18"))
        self.assertEqual(e.residents[LINK["tracker"]].confirmed, Status.HOME)
        e.gps_observation(LINK["tracker"], Status.NOT_HOME, T0-timedelta(days=1),
                          decision_at=T0+timedelta(minutes=1))
        self.assertEqual(e.residents[LINK["tracker"]].confirmed, Status.HOME)

    def test_new_gps_home_overrides_old_wifi_negative_in_hybrid(self):
        e = engine(Mode.HYBRID, "not_home")
        old = T0 - timedelta(days=1)
        e.gps_observation(LINK["tracker"], Status.NOT_HOME, old)
        poll_registered_wifi(
            e, [LINK], T0,
            lambda rec: WifiEvidence(True, "mac_verified", "enp6s18"))
        self.assertEqual(e.snapshot()["status"], "home")
        for minute in range(1, 17):
            now = T0 + timedelta(minutes=minute)
            poll_registered_wifi(e, [LINK], now,
                                 lambda rec: WifiEvidence(False, "no_reply"))
            e.expire(now)
            e.gps_observation(LINK["tracker"], Status.NOT_HOME, old, decision_at=now)
        self.assertEqual(e.snapshot()["status"], "not_home")
        newly_reported = T0 + timedelta(minutes=18)
        e.gps_observation(LINK["tracker"], Status.HOME, newly_reported,
                          decision_at=newly_reported)
        # A fresh GPS HOME is positive evidence of presence even when
        # older Wi-Fi diagnostics still show no connectivity.
        self.assertEqual(e.snapshot()["status"], "home")

    def test_wrong_mac_invalidates_wifi_home_without_claiming_away(self):
        e = engine(Mode.WIFI)
        poll_registered_wifi(e, [LINK], T0,
                             lambda record: WifiEvidence(True, "mac_verified", "enp6s18"))
        events = poll_registered_wifi(e, [LINK], T0+timedelta(minutes=1),
                                      lambda record: WifiEvidence(False, "mac_mismatch"))
        self.assertEqual(e.snapshot()["status"], "unavailable")
        self.assertEqual(e.residents[LINK["tracker"]].wifi_probe_result, "mac_mismatch")
        self.assertFalse(events)

    def test_snapshot_contains_no_ip_or_mac(self):
        e = engine(Mode.GPS)
        poll_registered_wifi(e, [LINK], T0,
                             lambda record: WifiEvidence(True, "mac_verified", "enp6s18"))
        snapshot = str(e.snapshot())
        self.assertNotIn(LINK["ip"], snapshot)
        self.assertNotIn(LINK["mac"], snapshot)
        self.assertIn("wifi_last_verified_at", snapshot)


if __name__ == "__main__":
    unittest.main()
