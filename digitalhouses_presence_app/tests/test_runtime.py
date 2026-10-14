import json
import queue
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError
from pathlib import Path
from types import SimpleNamespace

from app import MqttOutput, gps_from_ha_state, build_engine, load_options, friendly_tracker_name, observe_friendly_name, api_error_detail
from dh_presence.core import Mode, Status
from dh_presence.storage import load, save

NOW = datetime(2026, 10, 14, tzinfo=timezone.utc)


def options(**kw):
    return {
        "presence_mode": Mode.GPS, "wifi_absence_minutes": 15,
        "gps_freshness_seconds": 300, "gps_poll_interval_seconds": 30,
        "exclude_users": [], "residents": ["device_tracker.iphone"], **kw,
    }


class RuntimeSafetyTests(unittest.TestCase):
    def test_stale_tracker_never_becomes_absent(self):
        state = {"state": "not_home", "last_updated": (NOW - timedelta(minutes=20)).isoformat()}
        self.assertIs(gps_from_ha_state(state, NOW, 300, (43.2, 76.9))[0], Status.UNAVAILABLE)

    def test_recent_gps_with_valid_distance(self):
        state = {"state": "home", "last_updated": NOW.isoformat(),
                 "attributes": {"latitude": 43.2, "longitude": 76.9}}
        status, distance, _ = gps_from_ha_state(state, NOW, 300, (43.2, 76.9))
        self.assertIs(status, Status.HOME)
        self.assertLess(distance, 0.001)

    def test_unknown_tracker_never_absent(self):
        state = {"state": "unavailable", "last_updated": NOW.isoformat()}
        self.assertIs(gps_from_ha_state(state, NOW, 300, (43.2, 76.9))[0], Status.UNAVAILABLE)

    def test_corrupt_saved_state_fails(self):
        with tempfile.TemporaryDirectory() as d:
            file = Path(d) / "state.json"
            file.write_text("invalid", encoding="utf-8")
            with self.assertRaises(ValueError):
                load(str(file))

    def test_persistent_home_survives_save(self):
        with tempfile.TemporaryDirectory() as d:
            file = Path(d) / "state.json"
            sample = {"schema_version": 2, "residents": [{"tracker": "device_tracker.iphone", "confirmed": "home"}]}
            save(str(file), sample)
            self.assertEqual(load(str(file)), sample)

    def test_tracker_name_is_derived_from_HA(self):
        e = build_engine(options(), {"schema_version": 2, "residents": []})
        resident = e.residents["device_tracker.iphone"]
        self.assertEqual(resident.name, "iphone")
        self.assertTrue(observe_friendly_name(resident, {"attributes": {"friendly_name": "Сержан iPhone"}}))
        self.assertEqual(resident.name, "Сержан iPhone")
        self.assertFalse(observe_friendly_name(resident, {"attributes": {"friendly_name": "Сержан iPhone"}}))

    def test_legacy_state_is_not_guessed_for_an_unlinked_tracker(self):
        legacy = {"schema_version": 1, "residents": [{"user_id": "user-1", "confirmed": "home"}]}
        e = build_engine(options(), legacy)
        self.assertIs(e.residents["device_tracker.iphone"].confirmed, Status.UNAVAILABLE)

    def test_legacy_known_binding_preserves_last_confirmed(self):
        legacy = {"schema_version": 1, "residents": [{"user_id": "user-1", "confirmed": "home"}]}
        opts = options()
        opts["residents"] = [{"user_id": "user-1", "name": "iPhone", "device_id": "abc", "gps_tracker": "device_tracker.iphone"}]
        e = build_engine(opts, legacy)
        self.assertIs(e.residents["device_tracker.iphone"].confirmed, Status.HOME)

    def test_user_id_exclusion_for_legacy_binding(self):
        opts = options()
        opts["exclude_users"] = ["admin"]
        opts["residents"] = [
            {"user_id": "admin", "name": "Admin", "device_id": "a", "gps_tracker": "device_tracker.admin"},
            {"user_id": "user", "name": "Resident", "device_id": "b", "gps_tracker": "device_tracker.phone"}]
        e = build_engine(opts, {"schema_version": 2, "residents": []})
        self.assertEqual(list(e.residents), ["device_tracker.phone"])

    def test_exclusions_fail_loudly_for_tracker_only(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = options()
            cfg["presence_mode"] = "gps"
            cfg["exclude_users"] = ["admin-id"]
            f = Path(d) / "options.json"
            f.write_text(json.dumps(cfg), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "exclude_users"):
                load_options(str(f))

    def test_one_string_per_resident_in_options(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = options()
            cfg["presence_mode"] = "hybrid"
            f = Path(d) / "options.json"
            f.write_text(json.dumps(cfg), encoding="utf-8")
            out = load_options(str(f))
            self.assertIs(out["presence_mode"], Mode.HYBRID)

    def test_duplicate_trackers_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = options()
            cfg["presence_mode"] = "gps"
            cfg["residents"] = ["device_tracker.phone", "device_tracker.phone"]
            f = Path(d) / "options.json"
            f.write_text(json.dumps(cfg), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "only once"):
                load_options(str(f))

    def test_mqtt_mode_command_validation(self):
        output = object.__new__(MqttOutput)
        output.mode_commands = queue.SimpleQueue()
        for value in (b"away", b"", b"GPS", b"hybrid\x00"):
            output._message(None, None, SimpleNamespace(topic="DigitalHouses/Global/dh_presence_app/mode/set", payload=value))
        self.assertTrue(output.mode_commands.empty())
        output._message(None, None, SimpleNamespace(topic="DigitalHouses/Global/dh_presence_app/mode/set", payload=b"hybrid"))
        self.assertEqual(output.mode_commands.get_nowait(), "hybrid")
        output._message(None, None, SimpleNamespace(
            topic="DigitalHouses/Global/dh_presence_app/mode/set",
            payload=b"wifi", retain=True))
        self.assertTrue(output.mode_commands.empty())

    def test_api_failure_reports_http_status_without_credentials(self):
        exc = HTTPError("http://supervisor/core/api/config", 403, "Forbidden", None, None)
        detail = api_error_detail(exc)
        self.assertIn("403", detail)
        self.assertNotIn("supervisor", detail)

    def test_run_script_avoids_privileged_supervisor_timezone_query(self):
        root = Path(__file__).resolve().parents[1]
        script = (root / "rootfs/run.sh").read_text(encoding="utf-8")
        self.assertNotIn("bashio::supervisor.timezone)", script)
        self.assertIn('TZ="${TZ:-Asia/Almaty}"', script)

    def test_homeassistant_birth_requests_discovery(self):
        from app import WAKE
        output = object.__new__(MqttOutput)
        output.mode_commands = queue.SimpleQueue()
        output.discovery_requests = queue.SimpleQueue()
        WAKE.clear()
        output._message(None, None, SimpleNamespace(
            topic="homeassistant/status", payload=b"online", retain=False))
        self.assertEqual(output.discovery_requests.get_nowait(), "ha_birth")
        self.assertTrue(WAKE.is_set())
        WAKE.clear()

    def test_retained_birth_does_not_trigger_discovery(self):
        output = object.__new__(MqttOutput)
        output.mode_commands = queue.SimpleQueue()
        output.discovery_requests = queue.SimpleQueue()
        output._message(None, None, SimpleNamespace(
            topic="homeassistant/status", payload=b"online", retain=True))
        self.assertTrue(output.discovery_requests.empty())
