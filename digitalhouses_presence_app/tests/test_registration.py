"""Isolated registration safety tests: no live HA, LAN or internet required."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from dh_presence.registration import (
    ArpNoReply, active_arp_mac, completed_record, load_registry, normalized_mac, run_checked,
    put_registration, save_registry, validate_entry, normalize_resident_name,
)
from dh_presence.core import Mode, Status
from app import build_engine


def record(**overrides):
    value = {
        "user_id": "resident-ha-user",
        "user_name": "Жилец",
        "device_name": "13ProMAX .SKY",
        "device_id": "companion-phone-id",
        "entry_id": "ha-mobile-entry",
        "tracker": "device_tracker.iphone",
        "ip": "192.168.11.54",
        "mac": "88:b9:45:80:a7:55",
    }
    value.update(overrides)
    return value


def opts(**overrides):
    o = {
        "presence_mode": Mode.GPS,
        "wifi_absence_minutes": 15,
        "gps_freshness_seconds": 300,
        "residents": [],
        "resident_names": [],
        "exclude_users": [],
    }
    o.update(overrides)
    return o


class RegistrationTests(unittest.TestCase):
    def test_durable_registration_without_manual_resident_names(self):
        with tempfile.TemporaryDirectory() as d:
            p = str(Path(d) / "registration.json")
            residents = put_registration([], record())
            save_registry(p, residents)
            self.assertEqual(load_registry(p), residents)
            engine = build_engine(opts(), {"schema_version": 2, "residents": []}, load_registry(p))
            person = engine.residents["device_tracker.iphone"]
            self.assertEqual(person.user_name, "Жилец")
            self.assertEqual(person.name, "13ProMAX .SKY")
            self.assertIs(person.confirmed, Status.UNAVAILABLE)
            self.assertEqual(engine.snapshot()["residents"][person.key]["user_name"], "Жилец")

    def test_validate_cyrillic_name_and_reject_spoofed_labels(self):
        self.assertEqual(normalize_resident_name("  Сержан  "), "Сержан")
        self.assertEqual(normalize_resident_name("Анел  Айгүл"),
                         "Анел Айгүл")
        self.assertEqual(normalize_resident_name("O'Connor-Сержан"),
                         "O'Connor-Сержан")
        for invalid in (None, 42, [], {}, "", " ", "A\\nB",
                        "A\\u202eB", "<script>", "x" * 81):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                normalize_resident_name(invalid)

    def test_registry_label_changes_without_new_person_or_events(self):
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "registrations.json")
            current = put_registration([], record(user_name="Serzhan"))
            save_registry(path, current)
            original = load_registry(path)[0]
            modified = put_registration(current, {
                **original, "user_name": normalize_resident_name("  Сержан  ")})
            save_registry(path, modified)
            result = load_registry(path)[0]
            self.assertEqual(len(load_registry(path)), 1)
            self.assertEqual(result["user_name"], "Сержан")
            for unchanged in ("user_id", "tracker", "mac", "device_name",
                              "device_id", "entry_id", "ip"):
                self.assertEqual(result[unchanged], original[unchanged])
            # At runtime, the updated roster is reconciled in place with no
            # new source observations or fabricated arrival/departure.
            from app import reconcile_registration_roster
            engine = build_engine(opts(), {"schema_version": 2, "residents": []},
                                  [original])
            resident = engine.residents[original["tracker"]]
            self.assertEqual(resident.user_name, "Serzhan")
            self.assertTrue(reconcile_registration_roster(engine, opts(), [result], set()))
            self.assertIs(engine.residents[original["tracker"]], resident)
            self.assertEqual(resident.user_name, "Сержан")
            self.assertFalse(reconcile_registration_roster(engine, opts(), [result], set()))

    def test_re_registration_of_same_tracker_is_idempotent(self):
        r = put_registration([], record())
        self.assertEqual(put_registration(r, record()), r)
        newer = put_registration(r, record(ip="192.168.11.55"))
        self.assertEqual(len(newer), 1)
        self.assertEqual(newer[0]["ip"], "192.168.11.55")

    def test_wifi_tracker_binding_persists_across_restart_without_migration(self):
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "registration.json")
            original = record()
            save_registry(path, [original])
            self.assertNotIn("wifi_tracker", load_registry(path)[0])
            updated = record(wifi_tracker="device_tracker.13promax_sky_2")
            save_registry(path, put_registration(load_registry(path), updated))
            self.assertEqual(
                load_registry(path)[0]["wifi_tracker"],
                "device_tracker.13promax_sky_2")
            self.assertEqual(load_registry(path)[0]["user_id"], original["user_id"])
            self.assertEqual(len(load_registry(path)), 1)

    def test_registration_rejects_bad_or_shared_router_trackers(self):
        for invalid in ("", "sensor.router", "device_tracker.iphone",
                        "device_tracker.Invalid", 123, None):
            with self.subTest(invalid=invalid):
                if invalid is None:
                    continue  # None means absent (legacy record).
                with self.assertRaises(ValueError):
                    validate_entry(record(wifi_tracker=invalid))
        first = record(wifi_tracker="device_tracker.zte_iphone")
        other = record(tracker="device_tracker.another_phone",
                       device_id="another-phone-id",
                       mac="8a:43:3e:74:09:83",
                       wifi_tracker="device_tracker.zte_iphone")
        with self.assertRaisesRegex(ValueError, "already bound"):
            put_registration([first], other)

    def test_re_registration_cannot_transfer_existing_gps_or_replace_mac(self):
        existing = [record()]
        with self.assertRaisesRegex(ValueError, "another HA user"):
            put_registration(existing, record(user_id="other-user"))
        with self.assertRaisesRegex(ValueError, "different Wi-Fi MAC"):
            put_registration(existing, record(mac="8a:43:3e:74:09:83"))

    def test_reject_duplicate_mac_device_or_corrupt_registry(self):
        registered = [record()]
        for changed in [
            record(tracker="device_tracker.second"),
            record(tracker="device_tracker.second", mac="0a:01:02:03:04:05"),
        ]:
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                put_registration(registered, changed)
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "reg.json"
            f.write_text("{malformed")
            with self.assertRaises(ValueError):
                load_registry(str(f))

    def test_excluded_ha_user_is_not_enrolled(self):
        engine = build_engine(opts(exclude_users=["resident-ha-user"]),
                              {"schema_version": 2, "residents": []}, [record()])
        self.assertFalse(engine.residents)

    def test_old_tracker_only_user_is_fail_closed_when_exclusions_exist(self):
        engine = build_engine(opts(residents=["device_tracker.iphone"], exclude_users=["some-admin"]),
                              {"schema_version": 2, "residents": []})
        self.assertFalse(engine.residents)

    def test_existing_gps_tracker_gets_authenticated_user_name(self):
        engine = build_engine(opts(residents=["device_tracker.iphone"]),
                              {"schema_version": 2, "residents": []}, [record()])
        self.assertEqual(len(engine.residents), 1)
        self.assertEqual(engine.residents["device_tracker.iphone"].user_name, "Жилец")

    def test_invalid_or_multicast_mac_and_nonlocal_ip(self):
        for mac in ("ff:ff:ff:ff:ff:ff", "01:00:5e:00:00:00",
                    "00:00:00:00:00:00", "invalid"):
            with self.subTest(mac=mac), self.assertRaises(ValueError):
                normalized_mac(mac)
        with self.assertRaises(ValueError):
            validate_entry(record(ip="8.8.8.8"))

    def test_arp_from_local_route_and_fresh_reply(self):
        def output(args, timeout=5):
            if args[:4] == ["ip", "-4", "route", "get"]:
                return "192.168.11.54 dev enp6s18 src 192.168.11.33 uid 0\\n"
            if args[:4] == ["ip", "-j", "-4", "addr"]:
                return json.dumps([{"addr_info": [
                    {"family": "inet", "local": "192.168.11.33", "prefixlen": 24},
                ]}])
            if args[0] == "arping":
                return ("ARPING 192.168.11.54 from 192.168.11.33 enp6s18\\n"
                        "Unicast reply from 192.168.11.54 [88:B9:45:80:A7:55] 1.2ms\\n")
            raise AssertionError(args)
        with patch("dh_presence.registration.run_checked", side_effect=output):
            self.assertEqual(active_arp_mac("192.168.11.54"),
                             ("88:b9:45:80:a7:55", "enp6s18"))

    def test_no_arp_reply_or_offlink_route_cannot_register(self):
        with patch("dh_presence.registration.run_checked", side_effect=[
            "192.168.11.54 via 192.168.11.1 dev enp6s18 src 192.168.11.33\\n",
        ]) as tool:
            with self.assertRaises(ValueError):
                active_arp_mac("192.168.11.54")
            self.assertEqual(tool.call_count, 1)
        with patch("dh_presence.registration.run_checked", side_effect=[
            "192.168.11.54 dev enp6s18 src 192.168.11.33\\n",
            json.dumps([{"addr_info": [{"family": "inet", "local": "192.168.11.33", "prefixlen": 24}]}]),
            "ARPING 192.168.11.54... no replies\\n",
        ]):
            with self.assertRaises(ValueError):
                active_arp_mac("192.168.11.54")

    def test_completed_arp_zero_response_is_negative_not_probe_failure(self):
        cmd = ["arping", "-I", "enp6s18", "-c", "2", "-w", "3", "192.168.11.54"]
        with patch("dh_presence.registration.subprocess.run", return_value=SimpleNamespace(
                returncode=1, stdout="Sent 2 probes (2 broadcast(s))\nReceived 0 response(s)\n",
                stderr="")):
            with self.assertRaises(ArpNoReply):
                run_checked(cmd)
        with patch("dh_presence.registration.subprocess.run", return_value=SimpleNamespace(
                returncode=1, stdout="", stderr="operation not permitted")):
            with self.assertRaises(RuntimeError) as error:
                run_checked(cmd)
            self.assertNotIsInstance(error.exception, ArpNoReply)
        with patch("dh_presence.registration.subprocess.run", return_value=SimpleNamespace(
                returncode=2, stdout="Received 0 response(s)", stderr="")):
            with self.assertRaises(RuntimeError) as error:
                run_checked(cmd)
            self.assertNotIsInstance(error.exception, ArpNoReply)

    def test_conflicting_arp_macs_are_rejected(self):
        with patch("dh_presence.registration.run_checked", side_effect=[
            "192.168.11.54 dev enp6s18 src 192.168.11.33\\n",
            json.dumps([{"addr_info": [{"family": "inet", "local": "192.168.11.33", "prefixlen": 24}]}]),
            ("Unicast reply from 192.168.11.54 [88:B9:45:80:A7:55]\\n"
             "Unicast reply from 192.168.11.54 [88:B9:45:80:A7:56]\\n"),
        ]):
            with self.assertRaises(ValueError):
                active_arp_mac("192.168.11.54")
