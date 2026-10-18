import unittest

from dh_presence.core import Engine
from dh_presence.discovery import discovery, with_cleanup, topic, DISCOVERY


class TestDiscovery(unittest.TestCase):
    def test_one_device_dynamic_components(self):
        engine = Engine()
        engine.add("device_tracker.phone", "Resident")
        result = discovery("0.1.1", list(engine.residents.values()))
        self.assertEqual(result["device"]["identifiers"], ["dh_presence_app"])
        components = result["components"]
        self.assertEqual(components["event"]["platform"], "event")
        self.assertIn("residents_home", components)
        self.assertEqual(len([k for k in components if k.endswith("_distance")]), 1)
        self.assertEqual(components["mode"]["platform"], "select")
        self.assertEqual(components["mode"]["command_topic"], topic("mode/set"))

    def test_requested_device_name_and_wifi_sensor(self):
        e = Engine()
        e.add("device_tracker.13promax_sky", "13ProMAX .SKY")
        payload = discovery("0.1.9", list(e.residents.values()))
        self.assertEqual(payload["device"]["name"], "DH Presence")
        components = payload["components"]
        key = next(iter(e.residents.values())).key
        wifi = components[key + "_wifi_home"]
        self.assertEqual(wifi["default_entity_id"],
                         "binary_sensor.dh_presence_app_" + key + "_wifi_home")
        self.assertEqual(wifi["availability_mode"], "all")
        self.assertIn("wifi/" + key + "/availability", wifi["availability"][1]["topic"])
        self.assertEqual(components["refresh"]["payload_press"], "REFRESH")
        self.assertEqual(components["check_updates"]["payload_press"], "CHECK_UPDATES")
        self.assertEqual(components["card"]["state_topic"], topic("operations"))
        self.assertEqual(components[key + "_gps_home"]["json_attributes_topic"], topic("state"))
        self.assertIn("gps_reported_at", components[key + "_gps_home"]["json_attributes_template"])
        self.assertIn("gps_freshness_seconds", components["residents_home"]["json_attributes_template"])

    def test_discovery_tombstones(self):
        e = Engine()
        e.add("device_tracker.phone", "Resident")
        old = discovery("0.1.0", list(e.residents.values()))
        new = discovery("0.1.1", [])
        diff = with_cleanup(old, new)["components"]
        self.assertEqual(diff[next(k for k in diff if k.endswith("_gps_home"))], {"platform": "binary_sensor"})

    def test_single_device_topic_and_component_contract(self):
        e = Engine()
        e.add("device_tracker.13promax_sky", "Phone")
        config = discovery("0.1.4", list(e.residents.values()))
        self.assertEqual(DISCOVERY, "homeassistant/device/dh_presence_app/config")
        self.assertEqual(config["device"]["identifiers"], ["dh_presence_app"])
        self.assertEqual(config["origin"]["name"], "DigitalHouses Presence App")
        self.assertEqual(len(config["components"]), 18)
        for component in config["components"].values():
            self.assertIn(component["platform"], {"binary_sensor", "event", "select", "sensor", "button", "switch"})
            self.assertIn("unique_id", component)
