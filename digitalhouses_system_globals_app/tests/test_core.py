import tempfile
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from core import Store, Engine, ContractError, GLOBAL, PRODUCT


def at(s):
    return datetime.fromisoformat(s).astimezone(timezone.utc)


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "state.json"
        self.engine = Engine(Store(self.path))
        self.t = at("2026-11-26T20:00:00+05:00")

    def configure(self):
        self.engine.command(PRODUCT + "/config/set", {
            "auto_switch": True, "night_start": "23:00",
            "night_end": "07:00", "timezone": "Asia/Almaty"
        }, self.t)
        self.engine.command(GLOBAL + "/set", "off", self.t)

    def test_initial_has_no_defaults(self):
        out = self.engine.snapshot()
        self.assertEqual(out[0].payload, "")
        self.assertIsNone(out[1].payload["day"]["brightness"])
        self.assertIsNone(out[1].payload["night"]["color_temp_kelvin"])
        self.assertIsNone(out[1].payload["night"]["rgb_color"])
        self.assertNotIn("color_mode",out[1].payload["night"])

    def test_manual_day_at_night_and_restart(self):
        self.configure()
        out = self.engine.tick(at("2026-11-26T23:00:00+05:00"))
        self.assertEqual(out[-1].payload["event_type"], "night_mode_on")
        self.engine.command(GLOBAL + "/set", "off", at("2026-11-27T00:30:00+05:00"))
        e = Engine(Store(self.path))
        self.assertEqual(e.tick(at("2026-11-27T02:00:00+05:00")), [])
        self.assertEqual(e.state["night_mode"], "off")
        self.assertTrue(e.state["config"]["auto_switch"])
        self.assertEqual(e.tick(at("2026-11-27T07:00:00+05:00")), [])
        self.assertEqual(e.tick(at("2026-11-27T23:00:00+05:00"))[-1].payload["event_type"], "night_mode_on")

    def test_missed_boundary_and_duplicate_command(self):
        self.configure()
        e = Engine(Store(self.path))
        out = e.tick(at("2026-11-27T02:00:00+05:00"))
        self.assertEqual(e.state["night_mode"], "on")
        self.assertEqual([m.retain for m in out], [True, False])
        self.assertEqual(e.command(GLOBAL + "/set", "on", at("2026-11-27T03:00:00+05:00")), [])
        self.assertTrue(all(m.retain for m in e.snapshot()))

    def test_disable_schedule(self):
        self.configure()
        self.engine.command(PRODUCT + "/config/set", {"auto_switch": False}, self.t)
        self.assertEqual(self.engine.tick(at("2026-11-27T02:00:00+05:00")), [])

    def test_change_schedule_no_immediate_override(self):
        self.configure()
        self.engine.command(PRODUCT + "/config/set", {"night_start": "18:00"}, self.t)
        self.assertEqual(self.engine.tick(at("2026-11-26T21:00:00+05:00")), [])

    def test_profiles_independent_colors_atomic(self):
        p = PRODUCT + "/profiles/set"
        self.engine.command(p, {"day": {"color_temp_kelvin": 4000, "brightness": 0}}, self.t)
        out = self.engine.command(p, {"day": {"rgb_color": [0, 0, 255]}}, self.t)
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0].retain)
        day = out[0].payload["day"]
        self.assertEqual(day["color_temp_kelvin"], 4000)
        self.assertEqual(day["rgb_color"], [0, 0, 255])
        self.assertEqual(day["brightness"], 0)
        out = self.engine.command(p, {"night":{"color_temp_kelvin":2700,"rgb_color":[0,0,255]}}, self.t)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].payload["night"]["color_temp_kelvin"],2700)
        self.assertEqual(out[0].payload["night"]["rgb_color"],[0,0,255])
        self.engine.command(p, {"day":{"rgb_color":None}},self.t)
        self.assertEqual(self.engine.state["profiles"]["day"]["color_temp_kelvin"],4000)
        self.assertIsNone(self.engine.state["profiles"]["day"]["rgb_color"])
        before = self.path.read_bytes()
        with self.assertRaises(ContractError):
            self.engine.command(p, {"day": {"color_temp_kelvin": 3000, "rgb_color": [1,2,300]}, "night": {"brightness": 42}}, self.t)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertIsNone(self.engine.state["profiles"]["night"]["brightness"])
        self.assertEqual(Engine(Store(self.path)).state,self.engine.state)

    def test_migrate_v1_state_and_export_without_losing_values(self):
        self.configure()
        old=self.engine.state
        old["schema_version"]=1
        old["profiles"]["day"].update(color_mode="cct",color_temp_kelvin=4000,brightness=65,display_brightness=90,indicator_brightness=85)
        old["profiles"]["night"].update(color_mode="rgb",rgb_color=[0,0,255],volume=12,display_brightness=30,indicator_brightness=45)
        self.path.write_text(json.dumps(old))
        e=Engine(Store(self.path))
        self.assertEqual(e.state["schema_version"],3)
        self.assertEqual(e.state["config"],old["config"])
        self.assertEqual(e.state["schedule_cursor"],old["schedule_cursor"])
        self.assertEqual(e.state["night_mode"],old["night_mode"])
        self.assertEqual(e.state["profiles"]["day"]["color_temp_kelvin"],4000)
        self.assertEqual(e.state["profiles"]["night"]["rgb_color"],[0,0,255])
        self.assertNotIn("color_mode",e.state["profiles"]["day"])
        self.assertEqual(json.loads(self.path.read_text()),e.state)
        exported={k:old[k] for k in ("night_mode","config","profiles")}
        e.import_settings(exported,self.t)
        self.assertEqual(e.state["profiles"]["night"]["volume"],12)

    def test_migrate_v2_removes_only_obsolete_fields(self):
        self.configure()
        self.engine.command(PRODUCT+"/profiles/set",{"day":{"color_temp_kelvin":4000,"rgb_color":[255,255,255],"brightness":100,"volume":80},"night":{"color_temp_kelvin":2700,"rgb_color":[43,0,255],"brightness":40,"volume":30}},self.t)
        expected=self.engine.state
        old=self.engine.state
        old["schema_version"]=2
        for profile in old["profiles"].values():
            profile.update(display_brightness=90,indicator_brightness=85)
        self.path.write_text(json.dumps(old))
        e=Engine(Store(self.path))
        self.assertEqual(e.state,expected)
        self.assertEqual(json.loads(self.path.read_text()),expected)
        self.assertEqual(e.snapshot()[1].payload,expected["profiles"])
        for field in ("display_brightness","indicator_brightness"):
            with self.assertRaises(ContractError):
                e.command(PRODUCT+"/profiles/set",{"day":{field:10}},self.t)

    def test_profile_validation(self):
        p = PRODUCT + "/profiles/set"
        for invalid in [
            {"color_mode": "rgb"}, {"color_temp_kelvin": 1999}, {"brightness": True},
            {"rgb_color": [0, 0, 256]},
            {"rgb_color": [0, False, 0]},
            {"transition_seconds": float("nan")}, {"unknown": 1}
        ]:
            with self.subTest(invalid=invalid), self.assertRaises(ContractError):
                self.engine.command(p, {"day": invalid}, self.t)

    def test_config_validation_and_retained_command(self):
        with self.assertRaises(ContractError):
            self.engine.command(PRODUCT + "/config/set", {"auto_switch": True}, self.t)
        with self.assertRaises(ContractError):
            self.engine.command(GLOBAL + "/set", "on", self.t, retained=True)
        self.assertIsNone(self.engine.state["night_mode"])

    def test_corrupt_storage_is_not_silently_replaced(self):
        self.path.write_text("{bad")
        with self.assertRaises(ContractError):
            Engine(Store(self.path))
        self.assertEqual(self.path.read_text(), "{bad")


if __name__ == "__main__":
    unittest.main()
