import tempfile
import unittest
from pathlib import Path

from dh_presence.core import Engine, Mode, Status
from dh_presence.modes import ModeSelection
from dh_presence.discovery import discovery, topic


class ModeTests(unittest.TestCase):
    def test_config_initializes_and_ui_persists(self):
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "mode.json")
            first = ModeSelection(path, Mode.GPS)
            self.assertIs(first.selected, Mode.GPS)
            self.assertTrue(first.change("hybrid"))
            again = ModeSelection(path, Mode.GPS)
            self.assertIs(again.selected, Mode.HYBRID)
            self.assertFalse(again.change("hybrid"))

    def test_new_config_overrides_ui(self):
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "mode.json")
            original = ModeSelection(path, Mode.GPS)
            original.change("wifi")
            changed = ModeSelection(path, Mode.HYBRID)
            self.assertIs(changed.selected, Mode.HYBRID)

    def test_reject_invalid_mode_keeps_old(self):
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "mode.json")
            m = ModeSelection(path, Mode.GPS)
            with self.assertRaises(ValueError):
                m.change("away")
            self.assertIs(m.selected, Mode.GPS)

    def test_corrupt_saved_mode_not_silently_reset(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "mode.json"
            path.write_text("not json", encoding="utf-8")
            with self.assertRaises(ValueError):
                ModeSelection(str(path), Mode.GPS)

    def test_wifi_mode_without_wifi_source_is_unknown(self):
        e = Engine(mode=Mode.WIFI)
        e.add("device_tracker.iphone", "iPhone", {"confirmed": "home"})
        self.assertIs(e.overall(), Status.HOME)
        self.assertEqual(e.snapshot()["status"], "unavailable")

    def test_mode_discovery_single_device(self):
        d = discovery("0.1.1", [])
        select = d["components"]["mode"]
        self.assertEqual(select["platform"], "select")
        self.assertEqual(select["options"], ["gps", "wifi", "hybrid"])
        self.assertEqual(select["command_topic"], topic("mode/set"))
        self.assertEqual(select["state_topic"], topic("mode/state"))
        self.assertIs(select["retain"], False)
