"""HA router trackers are the sole runtime Wi-Fi authority."""
import unittest
from datetime import datetime, timedelta, timezone

from dh_presence.core import Engine, Mode, Status
from dh_presence.router import poll_router_trackers

START = datetime(2026, 10, 18, 0, 0, tzinfo=timezone.utc)
GPS = "device_tracker.13promax_sky"
WIFI = "device_tracker.13promax_sky_2"
MAC = "88:b9:45:80:a7:55"
REG = {"tracker": GPS, "wifi_tracker": WIFI, "mac": MAC,
       "user_id": "one", "user_name": "Serzhan"}


def state(value="home", *, entity=WIFI, mac=MAC, source="router", network=None):
    attrs = {"source_type": source, "mac_address": mac}
    if network is not None:
        attrs["network_type"] = network
    return {"entity_id": entity, "state": value, "attributes": attrs}


def setup(mode=Mode.WIFI):
    e = Engine(mode=mode, wifi_absence_minutes=1)
    e.add(GPS, "13ProMAX .SKY", user_name="Serzhan")
    return e


class RouterTrackerTests(unittest.TestCase):
    def test_exact_match_home_away_home_creates_only_real_transitions(self):
        e = setup()
        self.assertEqual(poll_router_trackers(e, [REG], [state("home")], START), [])
        self.assertEqual(e.residents[GPS].wifi, Status.HOME)
        self.assertEqual(e.residents[GPS].confirmed, Status.HOME)
        self.assertEqual(e.snapshot()["residents"][e.residents[GPS].key]["wifi_source"], "router")

        self.assertEqual(poll_router_trackers(
            e, [REG], [state("home")], START+timedelta(seconds=30)), [])
        away = poll_router_trackers(
            e, [REG], [state("not_home")], START+timedelta(minutes=1))
        self.assertEqual([x["event_type"] for x in away],
                         ["wifi_out", "departure"])
        self.assertEqual(e.residents[GPS].wifi, Status.NOT_HOME)
        restored = poll_router_trackers(
            e, [REG], [state("home")], START+timedelta(minutes=2))
        self.assertEqual([x["event_type"] for x in restored],
                         ["wifi_in", "arrival"])
        self.assertEqual(poll_router_trackers(
            e, [REG], [state("home")], START+timedelta(minutes=3)), [])

    def test_long_idle_home_does_not_expire_on_old_wifi_absence_setting(self):
        e = setup()
        poll_router_trackers(e, [REG], [state()], START)
        for hour in range(1, 49):
            now = START+timedelta(hours=hour)
            self.assertEqual(poll_router_trackers(e, [REG], [state()], now), [])
            self.assertEqual(e._decide(e.residents[GPS], now), Status.HOME)
        self.assertEqual(e.residents[GPS].wifi_probe_result, "router_home")

    def test_initial_away_is_baseline_not_departure(self):
        e = setup()
        self.assertEqual(poll_router_trackers(e, [REG], [state("not_home")], START), [])
        self.assertEqual(e.residents[GPS].wifi, Status.NOT_HOME)
        self.assertEqual(e.residents[GPS].wifi_probe_result, "router_not_home")
        result=poll_router_trackers(e, [REG], [state("home")], START+timedelta(seconds=30))
        self.assertEqual([x["event_type"] for x in result], ["wifi_in", "arrival"])

    def test_unavailable_source_does_not_report_absence_or_duplicate_in(self):
        e=setup()
        poll_router_trackers(e, [REG], [state()], START)
        for item, reason in (
            ([], "router_missing"),
            ([state("unavailable")], "router_unavailable"),
            ([state("unknown")], "router_unavailable"),
            ([state("home", mac="8a:43:3e:74:09:83")], "router_mac_or_source_mismatch"),
            ([state("home", source="gps")], "router_mac_or_source_mismatch"),
            ([state("home", network="LAN")], "router_mac_or_source_mismatch"),
        ):
            now=START+timedelta(minutes=1)
            self.assertEqual(poll_router_trackers(e, [REG], item, now), [])
            self.assertEqual(e.residents[GPS].wifi, Status.UNAVAILABLE)
            self.assertEqual(e.residents[GPS].wifi_probe_result, reason)
            self.assertEqual(poll_router_trackers(
                e, [REG], [state()], now+timedelta(seconds=1)), [])
        self.assertEqual(e.residents[GPS].wifi_last_decisive, Status.HOME)

    def test_duplicates_and_stale_binding_refused(self):
        e=setup()
        duplicate=[state(), state(entity="device_tracker.duplicate")]
        self.assertEqual(poll_router_trackers(e, [REG], duplicate, START), [])
        self.assertEqual(e.residents[GPS].wifi_probe_result, "router_ambiguous")
        self.assertEqual(poll_router_trackers(
            e, [REG], [state(entity="device_tracker.renamed")],
            START+timedelta(seconds=10)), [])
        self.assertEqual(e.residents[GPS].wifi_probe_result,
                         "router_mac_or_source_mismatch")

    def test_missing_enrollment_is_unknown_no_ip_fallback(self):
        e=setup()
        self.assertEqual(poll_router_trackers(e, [{**REG, "wifi_tracker": None}],
                                              [state()], START), [])
        self.assertEqual(e.residents[GPS].wifi_probe_result, "router_not_linked")
        self.assertEqual(poll_router_trackers(e, [], [state()], START), [])
        self.assertEqual(e.residents[GPS].wifi_probe_result, "router_not_registered")

    def test_gps_mode_independent_of_wifi_source(self):
        e=setup(Mode.GPS)
        poll_router_trackers(e, [REG], [state("not_home")], START)
        self.assertEqual(e.residents[GPS].confirmed, Status.UNAVAILABLE)
        self.assertEqual(e.residents[GPS].wifi, Status.NOT_HOME)

    def test_runtime_does_not_use_periodic_arp_or_ping_and_discovery_cleans_up(self):
        from pathlib import Path
        from dh_presence.discovery import discovery, with_cleanup
        import app
        path=Path(app.__file__)
        code=path.read_text(encoding="utf-8")
        self.assertIn("poll_router_trackers(", code)
        self.assertNotIn("poll_registered_wifi(", code)
        self.assertNotIn("probe_registered_phone(", code)
        self.assertNotIn("engine.expire(", code)
        self.assertNotIn('topic("probes/"', code)
        current=discovery("0.1.25", list(setup().residents.values()))
        self.assertNotIn("ping", current["components"])
        self.assertNotIn("arp", current["components"])
        old={"components": {"ping": {"platform": "switch"}, "arp": {"platform": "switch"}}}
        cleaned=with_cleanup(old,current)
        self.assertEqual(cleaned["components"]["ping"], {"platform": "switch"})
        self.assertEqual(cleaned["components"]["arp"], {"platform": "switch"})


if __name__ == "__main__":
    unittest.main()
