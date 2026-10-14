import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from app import gps_from_ha_state, build_engine, load_options
from dh_presence.core import Mode, Status
from dh_presence.storage import load, save

NOW = datetime(2026, 10, 14, tzinfo=timezone.utc)


class RuntimeSafetyTests(unittest.TestCase):
    def test_stale_tracker_never_becomes_absent(self):
        s = {"state": "not_home", "last_updated": (NOW - timedelta(minutes=20)).isoformat()}
        result = gps_from_ha_state(s, NOW, 300, (43.2, 76.9))
        self.assertIs(result[0], Status.UNAVAILABLE)

    def test_recent_gps_with_valid_distance(self):
        state = {"state": "home", "last_updated": NOW.isoformat(),
                 "attributes": {"latitude": 43.2, "longitude": 76.9}}
        status, dist, dt = gps_from_ha_state(state, NOW, 300, (43.2, 76.9))
        self.assertIs(status, Status.HOME)
        self.assertLess(dist, 0.001)

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
            sample = {"schema_version": 1, "residents": [{"user_id": "u", "confirmed": "home"}]}
            save(str(file), sample)
            self.assertEqual(load(str(file)), sample)

    def test_excluded_resident_not_registered(self):
        opts = {"presence_mode": Mode.GPS, "wifi_absence_minutes": 15,
                "gps_freshness_seconds": 300, "exclude_users": ["admin"],
                "residents": [
                    {"user_id": "admin", "name": "Admin", "device_id": "device", "gps_tracker": "device_tracker.admin"},
                    {"user_id": "user", "name": "Resident", "device_id": "device2", "gps_tracker": "device_tracker.phone"}]}
        e = build_engine(opts, {"schema_version": 1, "residents": []})
        self.assertEqual(list(e.residents), ["user"])
