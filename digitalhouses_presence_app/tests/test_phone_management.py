"""Admin-only deletion removes registration and stops the resident engine safely."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import build_engine, reconcile_registration_roster
from dh_presence.core import Status
from dh_presence.discovery import discovery, with_cleanup
from dh_presence.registration import (
    delete_registration, load_registry, load_registry_state,
    put_registration, save_registry,
)
from dh_presence.ui import HTML, handler_factory

SAMPLE = {
    "user_id": "resident-user-1", "user_name": "Serzhan",
    "device_name": "13ProMAX .SKY", "device_id": "device-a",
    "entry_id": "gps:device_tracker.phone_a",
    "tracker": "device_tracker.phone_a",
    "ip": "192.168.8.54", "mac": "88:b9:45:80:a7:55",
    "wifi_tracker": "device_tracker.wifi_a",
}


def config(**kwargs):
    return {
        "presence_mode": "gps", "wifi_absence_minutes": 15,
        "gps_freshness_seconds": 300, "residents": [],
        "exclude_users": [], "resident_names": [],
        **kwargs,
    }


class PhoneManagementTests(unittest.TestCase):
    def test_unregister_is_durable_even_if_legacy_config_keeps_tracker(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "registry.json")
            save_registry(path, [SAMPLE])
            original = build_engine(config(residents=["device_tracker.phone_a"]),
                                    {"schema_version": 2, "residents": []}, load_registry(path))
            self.assertEqual(len(original.residents), 1)
            self.assertTrue(next(iter(original.residents.values())).registered)
            removed = delete_registration(path, "device_tracker.phone_a")
            self.assertEqual(removed["device_name"], "13ProMAX .SKY")
            enrolled, suppressed = load_registry_state(path)
            self.assertEqual(enrolled, [])
            self.assertEqual(suppressed, {"device_tracker.phone_a"})
            self.assertTrue(reconcile_registration_roster(
                original, config(residents=["device_tracker.phone_a"]), enrolled, suppressed))
            self.assertEqual(original.residents, {})
            self.assertEqual(original.overall(), Status.UNAVAILABLE)
            self.assertEqual(original.persistent()["residents"], [])
            # Reboot, with same legacy config, must not resurrect phone.
            restarted = build_engine(config(residents=["device_tracker.phone_a"]),
                                     original.persistent(), enrolled, suppressed)
            self.assertFalse(restarted.residents)
            # A genuine new enrollment explicitly revokes the tombstone.
            enrolled = put_registration(enrolled, SAMPLE)
            save_registry(path, enrolled, disabled_trackers=suppressed - {"device_tracker.phone_a"})
            self.assertEqual(load_registry_state(path)[1], set())
            self.assertTrue(reconcile_registration_roster(
                original, config(residents=["device_tracker.phone_a"]), enrolled, set()))
            phone = original.residents["device_tracker.phone_a"]
            self.assertTrue(phone.registered)
            self.assertEqual(phone.confirmed, Status.UNAVAILABLE)

    def test_old_schema1_migrates_to_schema2_on_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry.json"
            path.write_text(json.dumps({"schema_version": 1, "residents": [SAMPLE]}))
            self.assertEqual(load_registry_state(str(path))[1], set())
            delete_registration(str(path), "device_tracker.phone_a")
            saved = json.loads(path.read_text())
            self.assertEqual(saved["schema_version"], 2)
            self.assertEqual(saved["disabled_trackers"], ["device_tracker.phone_a"])

    def test_invalid_delete_and_unknown_tracker_never_mutate(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry.json"
            save_registry(str(path), [SAMPLE])
            before = path.read_bytes()
            for name in ("", "device_tracker.other", "sensor.phone", "device_tracker.ADMIN",
                         "device_tracker.phone_a/../../"):
                if name == "device_tracker.other":
                    with self.assertRaises(LookupError):
                        delete_registration(str(path), name)
                else:
                    with self.assertRaises(ValueError):
                        delete_registration(str(path), name)
                self.assertEqual(path.read_bytes(), before)
            with self.assertRaises(ValueError):
                save_registry(str(path), [SAMPLE], disabled_trackers={"device_tracker.phone_a"})
            self.assertEqual(path.read_bytes(), before)

    def test_corrupt_tombstone_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry.json"
            for blocked in ("unexpected", ["device_tracker.x", "device_tracker.x"],
                            ["device_tracker.Bad"], ["device_tracker.phone_a"]):
                path.write_text(json.dumps({
                    "schema_version": 2, "residents": [SAMPLE], "disabled_trackers": blocked,
                }))
                with self.assertRaises(ValueError):
                    load_registry_state(str(path))

    def test_reconcile_retains_existing_state_on_unrelated_addition(self):
        engine = build_engine(config(), {"schema_version": 2, "residents": []}, [SAMPLE])
        engine.residents["device_tracker.phone_a"].confirmed = Status.HOME
        other = dict(SAMPLE, user_id="user2", user_name="Alina",
                     tracker="device_tracker.phone_b", device_id="device-b",
                     entry_id="gps:device_tracker.phone_b", ip="192.168.8.55",
                     mac="8a:43:3e:74:09:83", wifi_tracker="device_tracker.wifi_b")
        self.assertTrue(reconcile_registration_roster(engine, config(), [SAMPLE, other], set()))
        self.assertEqual(engine.residents["device_tracker.phone_a"].confirmed, Status.HOME)
        self.assertEqual(engine.residents["device_tracker.phone_b"].confirmed, Status.UNAVAILABLE)
        self.assertFalse(reconcile_registration_roster(engine, config(), [SAMPLE, other], set()))

    def test_discovery_cleanup_and_public_roster_after_unregister(self):
        engine = build_engine(config(), {"schema_version": 2, "residents": []}, [SAMPLE])
        old = discovery("0.1.29", list(engine.residents.values()))
        roster = engine.snapshot()["residents"]
        item = next(iter(roster.values()))
        self.assertTrue(item["registered"])
        self.assertEqual(item["registration_label"], "Serzhan (13ProMAX .SKY)")
        self.assertNotIn("192.168.8.", json.dumps(roster))
        self.assertNotIn("88:b9:45", json.dumps(roster))
        reconcile_registration_roster(engine, config(), [], {"device_tracker.phone_a"})
        new = discovery("0.1.29", list(engine.residents.values()))
        gone = with_cleanup(old, new)
        self.assertTrue(any(name.endswith("_gps_home") and comp == {"platform": "binary_sensor"}
                            for name, comp in gone["components"].items()))
        self.assertEqual(engine.snapshot()["residents"], {})

    def request(self, path="/api/admin/delete-registration", tracker="device_tracker.phone_a",
                headers=None, body=None, uid="admin", registry_path="/tmp/phone-registry.json"):
        cls = handler_factory("token", registry_path, set())
        req = object.__new__(cls)
        req.path = path
        payload = json.dumps({"tracker": tracker}).encode("utf-8") if body is None else body
        req.headers = {
            "X-Remote-User-Id": uid,
            "X-Remote-User-Display-Name": "Admin",
            "X-Presence-Request": "delete-registration",
            "Content-Type": "application/json",
            "Content-Length": str(len(payload)),
            **(headers or {}),
        }
        req.client_address = ("172.30.32.2", 12345)
        req.rfile = io.BytesIO(payload)
        answers = []
        req.reply = lambda status, data: answers.append((status, data))
        return req, answers

    def test_admin_delete_works_remotely_without_arp(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "registry.json")
            save_registry(path, [SAMPLE])
            req, answers = self.request(registry_path=path)
            # authenticated_ingress_user needs only Supervisor-provided identity,
            # never local-XFF context. Remote CF is valid for admin maintenance.
            with patch("dh_presence.ui.is_authorized_ha_admin", return_value=True):
                with patch("dh_presence.ui.active_arp_mac") as arp:
                    req.do_POST()
                    arp.assert_not_called()
            self.assertEqual(answers, [(200, {"deleted": True,
                                             "tracker": "device_tracker.phone_a"})])
            self.assertFalse(load_registry(path))
            self.assertIn("device_tracker.phone_a", load_registry_state(path)[1])

    def test_non_admin_and_failed_authorization_never_change_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "registry.json")
            save_registry(path, [SAMPLE])
            for authorized in (False,):
                req, answers = self.request(registry_path=path, uid="resident")
                with patch("dh_presence.ui.is_authorized_ha_admin",
                           return_value=authorized):
                    req.do_POST()
                self.assertEqual(answers[0][0], 403)
            self.assertEqual(load_registry(path), [SAMPLE])

    def test_header_and_payload_rejection_no_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "registry.json")
            save_registry(path, [SAMPLE])
            cases = [
                {"headers": {"X-Presence-Request": "register"}},
                {"headers": {"Content-Type": "text/plain"}},
                {"body": json.dumps({"tracker": "device_tracker.phone_a",
                                     "extra": "bad"}).encode()},
                {"body": b"invalid-json"},
                {"tracker": "device_tracker.other"},
            ]
            for options in cases:
                req, answers = self.request(registry_path=path, **options)
                with patch("dh_presence.ui.is_authorized_ha_admin", return_value=True):
                    req.do_POST()
                self.assertIn(answers[0][0], (400, 403, 404))
                self.assertEqual(load_registry(path), [SAMPLE])

    def test_public_dashboard_and_private_admin_ui_contract(self):
        from pathlib import Path
        base = Path(__file__).resolve().parents[1]
        card = (base / "examples/lovelace/presence_registered_phones_markdown_ru.yaml").read_text()
        dash = (base / "examples/lovelace/dh_presence_app_dashboard.yaml").read_text()
        self.assertIn("phone.registration_label", card)
        self.assertIn("selectattr('registered')", card)
        self.assertIn("phone.registration_label", dash)
        for forbidden in ("phone.ip", "phone.mac", "api/admin/delete-registration"):
            self.assertNotIn(forbidden, card)
        self.assertIn('is_authorized_ha_admin(context["user_id"], token)',
                      (base / "rootfs/app/dh_presence/ui.py").read_text())
        for marker in (
                       "X-Presence-Request", "delete-registration",
                       "Удалить регистрацию", "confirm(", "q('adminDebug').hidden=true"):
            self.assertIn(marker, HTML)


if __name__ == "__main__":
    unittest.main()
