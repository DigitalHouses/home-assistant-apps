"""Manual fan maximum RPM is a persisted observation setting, never PWM control."""
from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.collectors.cooling import FanSnapshot
from app.config import MqttConfig
from app.fan_max_rpm import FanMaxRpmRegistry
from app.fan_runtime import FanAwareRuntime
from app.identity import HostIdentity
from app.mqtt_bridge import MqttEvents
from app.runtime_problems import ProblemAwareRuntime
from app.runtime_settings import RuntimeSettings
from app.state_store import StateStore
from app.topics import build_topics


def fan(fan_id="it8613_it87_2608_fan2", rpm=850):
    return FanSnapshot(
        fan_id=fan_id, chip="it8613", chip_display_name="it8613",
        source_device="it87.2608", fan_name="fan2", fan_index=2,
        label="Fan 2", display_name="Fan 2 RPM", rpm=rpm,
        available=rpm is not None, input_path="/sys/class/hwmon/hwmon3/fan2_input",
    )


def mqtt_events():
    config = MqttConfig(
        host="mqtt", port=1883, username="", password="",
        topic_prefix="DigitalHouses/Global/digitalhouses_pve_agent",
        discovery_prefix="homeassistant", keepalive_seconds=60,
    )
    identity = HostIdentity(
        machine_id="0123456789abcdef0123456789abcdef",
        instance_id="node_a", hostname="pve", node_name="PVE",
    )
    return MqttEvents(build_topics(config, identity), RuntimeSettings())


class TestManualFanMaxRpm(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.registry = FanMaxRpmRegistry(StateStore(self.root / "fan_max_rpm.json"))
        self.id = fan().fan_id

    def test_manual_value_survives_restart_and_isolated_per_fan(self):
        self.assertEqual(self.registry.presentation(fan())["speed_percent"], None)
        self.assertEqual(self.registry.get(self.id), 0)
        self.assertTrue(self.registry.set(self.id, 1700))
        self.assertEqual(self.registry.presentation(fan())["speed_percent"], 50)
        self.assertEqual(self.registry.presentation(fan(rpm=0))["speed_percent"], 0)
        self.assertEqual(self.registry.presentation(fan(rpm=1900))["speed_percent"], 100)
        self.assertEqual(self.registry.get("another_fan"), 0)
        restarted = FanMaxRpmRegistry(StateStore(self.root / "fan_max_rpm.json"))
        self.assertEqual(restarted.get(self.id), 1700)
        self.assertFalse(restarted.set(self.id, 1700))
        self.assertTrue(restarted.set(self.id, 0))
        self.assertIsNone(restarted.presentation(fan())["speed_percent"])
        self.assertEqual(self.registry.get(self.id), 0)

    def test_invalid_limits_and_ids_never_saved(self):
        for bad in (-1, 30001, 1.5, True, "1700"):
            with self.assertRaises(ValueError):
                self.registry.set(self.id, bad)
        with self.assertRaises(ValueError):
            self.registry.set("../fan2", 1700)
        self.assertFalse((self.root / "fan_max_rpm.json").exists())

    def test_mqtt_command_is_saved_for_confirmed_fan_and_republished(self):
        bridge = mqtt_events()
        (self.root / "fans.json").write_text(
            '{"confirmed":["it8613_it87_2608_fan2"]}', encoding="utf-8",
        )
        runtime = object.__new__(FanAwareRuntime)
        runtime.bridge = bridge
        runtime.fan_max_rpm_registry = self.registry
        runtime.fan_presence_state_store = StateStore(self.root / "fans.json")
        runtime.fan_source = lambda: (fan(),)
        runtime.log = logging.getLogger(__name__)
        runtime.run_collection = MagicMock(return_value=True)
        command = bridge.topics.fan_max_rpm_prefix + "/" + self.id + "/max_rpm/set"
        self.assertTrue(bridge.handle_message(command, b"1700"))
        with patch.object(ProblemAwareRuntime, "process_events", return_value=False):
            self.assertTrue(runtime.process_events())
        self.assertEqual(self.registry.get(self.id), 1700)
        runtime.run_collection.assert_called_once_with(names=("fans",), force=True)

    def test_unknown_fan_command_does_not_persist(self):
        bridge = mqtt_events()
        (self.root / "fans.json").write_text('{"confirmed":[]}', encoding="utf-8")
        runtime = object.__new__(FanAwareRuntime)
        runtime.bridge = bridge
        runtime.fan_max_rpm_registry = self.registry
        runtime.fan_presence_state_store = StateStore(self.root / "fans.json")
        runtime.fan_source = lambda: (fan(),)
        runtime.log = logging.getLogger(__name__)
        runtime.run_collection = MagicMock()
        command = bridge.topics.fan_max_rpm_prefix + "/" + self.id + "/max_rpm/set"
        bridge.handle_message(command, b"1700")
        with patch.object(ProblemAwareRuntime, "process_events", return_value=False):
            self.assertTrue(runtime.process_events())
        self.assertEqual(self.registry.get(self.id), 0)
        runtime.run_collection.assert_not_called()


if __name__ == "__main__":
    unittest.main()
