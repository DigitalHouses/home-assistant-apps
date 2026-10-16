"""Household-wide PING/ARP MQTT switches and conservative combined evidence."""
import json
import queue
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import MqttOutput, WAKE, publish_snapshot
from dh_presence.core import Engine, Mode, Status
from dh_presence.discovery import discovery, topic
from dh_presence.probes import ProbeSelection, DEFAULTS
from dh_presence.registration import ArpNoReply
from dh_presence.wifi import WifiEvidence, probe_registered_phone, active_ping_ip, poll_registered_wifi

NOW = datetime(2026, 10, 17, 6, 0, tzinfo=timezone.utc)
PHONE = {"tracker": "device_tracker.iphone", "ip": "192.168.11.54",
         "mac": "88:b9:45:80:a7:55"}
MATCH = lambda _: ("88:b9:45:80:a7:55", "vmbr0")
MISS = lambda _: (_ for _ in ()).throw(ArpNoReply("zero response"))
BAD = lambda _: (_ for _ in ()).throw(RuntimeError("No route"))


class FakeOutput:
    def __init__(self):
        self.calls = {}
    def publish(self, where, value, **kwargs):
        self.calls[where] = value
        return True


class ProbeSwitchTests(unittest.TestCase):
    def test_default_arp_on_ping_off_and_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "probes.json")
            a = ProbeSelection(path)
            self.assertEqual(a.enabled, {"ping": False, "arp": True})
            self.assertFalse(a.change("arp", "ON"))
            self.assertTrue(a.change("ping", "ON"))
            self.assertTrue(a.change("arp", "OFF"))
            b = ProbeSelection(path)
            self.assertEqual(b.enabled, {"ping": True, "arp": False})
            self.assertEqual(b.mqtt_state("arp"), "OFF")
            self.assertEqual(json.loads(Path(path).read_text())["schema_version"], 1)

    def test_invalid_retained_or_corrupt_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "probes.json"
            a = ProbeSelection(str(file))
            for key, value in (("other", "ON"), ("ping", "on"), ("arp", "TRUE")):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    a.change(key, value)
            file.write_text('{"schema_version":1,"enabled":{"arp":true}}', encoding="utf-8")
            with self.assertRaises(ValueError):
                ProbeSelection(str(file))

    def test_discovery_two_household_switches_not_per_phone(self):
        e = Engine()
        e.add(PHONE["tracker"], "iPhone")
        e.add("device_tracker.android", "Android")
        cfg = discovery("0.1.22", list(e.residents.values()))
        keys = [k for k,v in cfg["components"].items() if v["platform"] == "switch"]
        self.assertEqual(sorted(keys), ["arp", "notify_gps", "notify_presence",
                                         "notify_wifi", "ping"])
        for key in DEFAULTS:
            component = cfg["components"][key]
            self.assertEqual(component["default_entity_id"], "switch.dh_presence_app_" + key)
            self.assertEqual(component["command_topic"], topic("probes/" + key + "/set"))
            self.assertEqual(component["state_topic"], topic("probes/" + key + "/state"))
            self.assertFalse(component["retain"])
        self.assertEqual(cfg["device"]["identifiers"], ["dh_presence_app"])

    def test_commands_ignore_retained_malformed_and_enqueue_valid(self):
        out = object.__new__(MqttOutput)
        out.probe_commands = queue.SimpleQueue()
        WAKE.clear()
        def message(key, payload, retain=False):
            out._message(None, None, SimpleNamespace(
                topic=topic("probes/" + key + "/set"), payload=payload, retain=retain))
        message("ping", b"ON", retain=True)
        message("ping", b"yes")
        message("arp", b"off")
        self.assertTrue(out.probe_commands.empty())
        message("ping", b"ON")
        message("arp", b"OFF")
        self.assertEqual(out.probe_commands.get_nowait(), ("ping", "ON"))
        self.assertEqual(out.probe_commands.get_nowait(), ("arp", "OFF"))
        self.assertTrue(WAKE.is_set())
        WAKE.clear()

    def test_snapshot_keeps_switches_and_source_state_in_same_device(self):
        e = Engine()
        e.add(PHONE["tracker"], "iPhone")
        e.gps_observation(PHONE["tracker"], Status.HOME, NOW)
        with tempfile.TemporaryDirectory() as directory:
            probes = ProbeSelection(str(Path(directory) / "probes.json"))
            probes.change("ping", "ON")
            output = FakeOutput()
            with patch("app.publish_controls", return_value=True):
                self.assertTrue(publish_snapshot(
                    output, e, "0.1.22", NOW.isoformat(), None, None, None, probes))
            self.assertEqual(output.calls[topic("probes/ping/state")], "ON")
            self.assertEqual(output.calls[topic("probes/arp/state")], "ON")
            self.assertEqual(output.calls[topic("state")]["status"], "home")

    def test_arp_only_regression(self):
        self.assertEqual(probe_registered_phone(PHONE, MATCH), WifiEvidence(
            True, "mac_verified", "vmbr0"))
        self.assertEqual(probe_registered_phone(PHONE, MISS), WifiEvidence(False, "no_reply"))

    def test_ping_only_replies_misses_and_errors(self):
        self.assertEqual(probe_registered_phone(
            PHONE, BAD, ping_probe=lambda ip: True, use_arp=False, use_ping=True),
            WifiEvidence(True, "ping_reply"))
        self.assertEqual(probe_registered_phone(
            PHONE, BAD, ping_probe=lambda ip: False, use_arp=False, use_ping=True),
            WifiEvidence(False, "no_reply"))
        self.assertEqual(probe_registered_phone(
            PHONE, BAD, ping_probe=BAD, use_arp=False, use_ping=True),
            WifiEvidence(False, "ping_error"))

    def test_both_modes_any_positive_all_negative_and_infrastructure_unknown(self):
        combos = [
            (MATCH, lambda _: False, True, "mac_verified"),
            (MISS, lambda _: True, True, "ping_reply"),
            (MATCH, lambda _: True, True, "mac_and_ping_verified"),
            (MISS, lambda _: False, False, "no_reply"),
            (BAD, lambda _: False, False, "probe_error"),
            (MISS, BAD, False, "ping_error"),
        ]
        for arp, ping, positive, reason in combos:
            with self.subTest(reason=reason):
                evidence = probe_registered_phone(PHONE, arp, ping_probe=ping,
                                                   use_arp=True, use_ping=True)
                self.assertEqual((evidence.positive, evidence.reason), (positive, reason))

    def test_mac_mismatch_never_accepted_even_with_successful_ping(self):
        alien = lambda _: ("02:aa:bb:cc:dd:ee", "vmbr0")
        evidence = probe_registered_phone(
            PHONE, alien, ping_probe=lambda _: True, use_arp=True, use_ping=True)
        self.assertEqual(evidence, WifiEvidence(False, "mac_mismatch"))

    def test_disabled_methods_do_not_invoke_network(self):
        self.assertEqual(probe_registered_phone(
            PHONE, BAD, ping_probe=BAD, use_arp=False, use_ping=False),
            WifiEvidence(False, "disabled"))

    def test_ping_output_requires_completed_reply_or_loss_summary(self):
        def fake(rc, stdout, stderr=""):
            return lambda *args, **kwargs: SimpleNamespace(
                returncode=rc, stdout=stdout, stderr=stderr)
        self.assertTrue(active_ping_ip(PHONE["ip"], fake(
            0, "1 packets transmitted, 1 received, 0% packet loss")))
        self.assertTrue(active_ping_ip(PHONE["ip"], fake(
            0, "1 packets transmitted, 1 packets received, 0% packet loss")))
        self.assertFalse(active_ping_ip(PHONE["ip"], fake(
            1, "1 packets transmitted, 0 received, 100% packet loss")))
        with self.assertRaises(RuntimeError):
            active_ping_ip(PHONE["ip"], fake(2, "0 received", "unreachable"))
        with self.assertRaises(RuntimeError):
            active_ping_ip(PHONE["ip"], fake(1, "", "command failed"))

    def test_switching_methods_no_synthetic_events_or_old_wifi_home(self):
        e = Engine(mode=Mode.WIFI, wifi_absence_minutes=1)
        e.add(PHONE["tracker"], "iPhone")
        e.gps_observation(PHONE["tracker"], Status.HOME, NOW)
        poll_registered_wifi(e, [PHONE], NOW, lambda _: WifiEvidence(True, "mac_verified"))
        self.assertEqual(e.overall(), Status.HOME)
        e.reset_wifi_methods(NOW + timedelta(seconds=5), disabled=True)
        self.assertEqual(e.overall(), Status.UNAVAILABLE)
        self.assertEqual(e.residents[PHONE["tracker"]].wifi_probe_result, "disabled")
        first = poll_registered_wifi(e, [PHONE], NOW + timedelta(minutes=1),
                                     lambda _: WifiEvidence(True, "ping_reply"))
        self.assertEqual(first, [])
        self.assertEqual(e.overall(), Status.HOME)
        self.assertEqual(poll_registered_wifi(
            e, [PHONE], NOW + timedelta(minutes=2),
            lambda _: WifiEvidence(True, "ping_reply")), [])

    def test_hybrid_switch_change_falls_back_to_known_gps(self):
        e = Engine(mode=Mode.HYBRID)
        e.add(PHONE["tracker"], "iPhone")
        e.gps_observation(PHONE["tracker"], Status.NOT_HOME, NOW)
        poll_registered_wifi(e, [PHONE], NOW, lambda _: WifiEvidence(True, "mac_verified"))
        self.assertEqual(e.overall(), Status.HOME)
        e.reset_wifi_methods(NOW + timedelta(seconds=1), disabled=True)
        self.assertEqual(e.overall(), Status.NOT_HOME)
        self.assertEqual(e.residents[PHONE["tracker"]].wifi, Status.UNAVAILABLE)


if __name__ == "__main__":
    unittest.main()
