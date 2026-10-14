import json
import queue
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError
from pathlib import Path
from types import SimpleNamespace

from app import MqttOutput, gps_from_ha_state, build_engine, load_options, friendly_tracker_name, observe_friendly_name, api_error_detail, audit_ha_discovery
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
    def test_old_valid_tracker_retains_last_known_away(self):
        when = NOW - timedelta(days=2)
        state = {"state": "not_home", "last_updated": when.isoformat()}
        status, distance, observed = gps_from_ha_state(state, NOW, 300, (43.2, 76.9))
        self.assertIs(status, Status.NOT_HOME)
        self.assertIsNone(distance)
        self.assertEqual(observed, when)

    def test_last_reported_recognizes_fresh_unchanged_tracker(self):
        state = {
            "state": "not_home",
            "last_updated": (NOW - timedelta(days=2)).isoformat(),
            "last_reported": NOW.isoformat(),
        }
        status, distance, timestamp = gps_from_ha_state(state, NOW, 300, (43.2, 76.9))
        self.assertIs(status, Status.NOT_HOME)
        self.assertIsNone(distance)
        self.assertEqual(timestamp, NOW)

    def test_old_report_is_still_last_known_home_with_distance(self):
        when = NOW - timedelta(days=2)
        state = {
            "state": "home",
            "last_updated": (NOW - timedelta(days=3)).isoformat(),
            "last_reported": when.isoformat(),
            "attributes": {"latitude": 43.21, "longitude": 76.9},
        }
        status, distance, observed = gps_from_ha_state(state, NOW, 300, (43.2, 76.9))
        self.assertIs(status, Status.HOME)
        self.assertIsInstance(distance, float)
        self.assertEqual(observed, when)

    def test_future_report_is_not_trusted(self):
        state = {"state": "home", "last_reported": (NOW + timedelta(minutes=2)).isoformat()}
        self.assertIs(gps_from_ha_state(state, NOW, 300, (43.2, 76.9))[0],
                      Status.UNAVAILABLE)

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

    def test_unbound_trackers_cannot_bypass_excluded_user_policy(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = options()
            cfg["presence_mode"] = "gps"
            cfg["exclude_users"] = ["admin-id"]
            f = Path(d) / "options.json"
            f.write_text(json.dumps(cfg), encoding="utf-8")
            loaded = load_options(str(f))
            engine = build_engine(loaded, {"schema_version": 2, "residents": []})
            # A legacy string has no authenticated HA-user binding. Safe
            # default is to skip it rather than monitor an excluded admin.
            self.assertFalse(engine.residents)

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

    def test_mqtt_operation_commands_reject_retained_or_unknown(self):
        from app import WAKE
        output = object.__new__(MqttOutput)
        output.operation_commands = queue.SimpleQueue()
        WAKE.clear()
        output._message(None, None, SimpleNamespace(
            topic="DigitalHouses/Global/dh_presence_app/command",
            payload=b"REFRESH", retain=True))
        self.assertTrue(output.operation_commands.empty())
        output._message(None, None, SimpleNamespace(
            topic="DigitalHouses/Global/dh_presence_app/command",
            payload=b"RESTART", retain=False))
        self.assertTrue(output.operation_commands.empty())
        output._message(None, None, SimpleNamespace(
            topic="DigitalHouses/Global/dh_presence_app/command",
            payload=b"CHECK_UPDATES", retain=False))
        self.assertEqual(output.operation_commands.get_nowait(), "CHECK_UPDATES")
        self.assertTrue(WAKE.is_set())
        WAKE.clear()

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

    def test_ha_discovery_audit_found(self):
        config = {"components": ["mqtt", "api"]}
        states = [{"entity_id": "sensor.dh_presence_app_version", "state": "0.1.6"}]
        with patch("app.http_json", side_effect=[config, states]) as mock_api:
            status, detail = audit_ha_discovery("dummy-token")
        self.assertEqual(status, "found")
        self.assertIn("sensor.dh_presence_app_version", detail)
        self.assertEqual(mock_api.call_count, 2)

    def test_ha_discovery_audit_mqtt_not_loaded(self):
        config = {"components": ["api", "mobile_app"]}
        with patch("app.http_json", return_value=config) as mock_api:
            status, detail = audit_ha_discovery("dummy-token")
        self.assertEqual(status, "mqtt_not_loaded")
        self.assertIn("MQTT integration", detail)
        self.assertEqual(mock_api.call_count, 1)

    def test_ha_discovery_audit_missing_expected_entities(self):
        config = {"components": ["mqtt", "api"]}
        states = [{"entity_id": "sensor.dh_internet_app_version", "state": "0.1.23"}]
        with patch("app.http_json", side_effect=[config, states]):
            status, detail = audit_ha_discovery("dummy-token")
        self.assertEqual(status, "not_found")
        self.assertIn("could be renamed", detail)

    def test_ha_discovery_audit_malformed_state_response(self):
        with patch("app.http_json", side_effect=[{"components": ["mqtt"]}, {"error": "not a list"}]):
            with self.assertRaises(ValueError):
                audit_ha_discovery("dummy-token")

    def test_one_time_tracker_to_user_name_binding(self):
        config = options(resident_names=[
            {"device_tracker": "device_tracker.iphone", "user_name": "Имя жильца"}
        ])
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "options.json"
            config["presence_mode"] = "gps"
            f.write_text(json.dumps(config), encoding="utf-8")
            loaded = load_options(str(f))
        e = build_engine(loaded, {"schema_version": 2, "residents": []})
        resident = e.residents["device_tracker.iphone"]
        self.assertEqual(resident.user_name, "Имя жильца")
        self.assertEqual(resident.name, "iphone")
        self.assertTrue(observe_friendly_name(resident, {
            "attributes": {"friendly_name": "iPhone 13 Pro"}
        }))
        self.assertEqual(resident.name, "iPhone 13 Pro")
        self.assertEqual(resident.user_name, "Имя жильца")
        self.assertEqual(e.snapshot()["residents"][resident.key]["user_name"], "Имя жильца")

    def test_empty_mapping_keeps_legacy_tracker_friendly_name(self):
        e = build_engine(options(), {"schema_version": 2, "residents": []})
        resident = e.residents["device_tracker.iphone"]
        self.assertIsNone(resident.user_name)
        self.assertEqual(resident.name, "iphone")

    def test_resident_names_invalid_input_rejected(self):
        bad = [
            [{"device_tracker": "device_tracker.unknown", "user_name": "Somebody"}],
            [{"device_tracker": "person.somebody", "user_name": "Somebody"}],
            [{"device_tracker": "device_tracker.iphone", "user_name": ""}],
            [{"device_tracker": "device_tracker.iphone", "user_name": "   "}],
            [{"device_tracker": "device_tracker.iphone", "user_name": "X"},
             {"device_tracker": "device_tracker.iphone", "user_name": "Y"}],
            [{"device_tracker": "device_tracker.iphone", "user_name": "X", "extra": 1}],
            "not a list",
        ]
        for case in bad:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as d:
                config = options(resident_names=case)
                config["presence_mode"] = "gps"
                f = Path(d) / "options.json"
                f.write_text(json.dumps(config), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_options(str(f))

    def test_resident_name_mapping_survives_restored_confirmed_state(self):
        e = build_engine(options(resident_names=[
            {"device_tracker": "device_tracker.iphone", "user_name": "Имя жильца"}
        ]), {"schema_version": 2, "residents": [
            {"tracker": "device_tracker.iphone", "confirmed": "home"}
        ]})
        resident = e.residents["device_tracker.iphone"]
        self.assertEqual(resident.confirmed, Status.HOME)
        self.assertEqual(resident.user_name, "Имя жильца")
