import unittest
from dh_presence.core import Engine
from dh_presence.discovery import discovery, with_cleanup


class TestDiscovery(unittest.TestCase):
    def test_one_device_dynamic_components(self):
        engine = Engine()
        engine.add("user-1", "Resident", "companion-1", "device_tracker.phone")
        result = discovery("0.1.0", list(engine.residents.values()))
        self.assertEqual(result["device"]["identifiers"], ["dh_presence_app"])
        components = result["components"]
        self.assertEqual(components["event"]["platform"], "event")
        self.assertIn("residents_home", components)
        self.assertEqual(len([k for k in components if k.endswith("_distance")]), 1)

    def test_discovery_tombstones(self):
        e = Engine()
        e.add("user-1", "Resident", "companion-1", "device_tracker.phone")
        old = discovery("0.1.0", list(e.residents.values()))
        new = discovery("0.1.0", [])
        diff = with_cleanup(old, new)["components"]
        self.assertEqual(diff[next(k for k in diff if k.endswith("_gps_home"))], {"platform": "binary_sensor"})
