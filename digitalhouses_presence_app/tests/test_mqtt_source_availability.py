"""MQTT source state: unknown does not become a false OFF/history event."""
import unittest
from unittest.mock import patch

from dh_presence.core import Engine, Status
from dh_presence.discovery import discovery, topic
from app import publish_snapshot


class FakeMQTT:
    def __init__(self):
        self.calls = []

    def publish(self, destination, payload, **kwargs):
        self.calls.append((destination, payload))
        return True

    def index(self, destination):
        return next(i for i, (t, _) in enumerate(self.calls) if t == destination)


class MqttSourceAvailabilityTests(unittest.TestCase):
    def engine(self):
        e = Engine()
        e.add("device_tracker.13promax_sky", "13ProMAX .SKY", user_name="Serzhan")
        person = next(iter(e.residents.values()))
        person.confirmed = Status.HOME
        person.gps = Status.HOME
        return e, person

    def publish(self, engine):
        output = FakeMQTT()
        with patch("app.publish_controls", return_value=True):
            self.assertTrue(publish_snapshot(output, engine, "0.1.16",
                                             "2026-10-15T00:00:00+00:00", None, None))
        return output

    def test_unknown_wifi_is_marked_offline_before_snapshot(self):
        e, resident = self.engine()
        output = self.publish(e)
        availability = topic("wifi/" + resident.key + "/availability")
        self.assertEqual(output.calls[output.index(availability)][1], "offline")
        self.assertLess(output.index(availability), output.index(topic("state")))
        self.assertLess(output.index(topic("presence_observed")),
                        output.index(topic("state")))

    def test_recovery_is_marked_online_before_home_snapshot(self):
        e, resident = self.engine()
        resident.wifi = Status.HOME
        output = self.publish(e)
        availability = topic("wifi/" + resident.key + "/availability")
        self.assertEqual(output.calls[output.index(availability)][1], "online")
        self.assertLess(output.index(availability), output.index(topic("state")))
        self.assertEqual(output.calls[output.index(topic("state"))][1]
                         ["residents"][resident.key]["wifi"], "home")

    def test_unknown_is_not_false_off_in_mqtt_discovery_templates(self):
        e, person = self.engine()
        components = discovery("0.1.16", [person])["components"]
        for key in ("residents_home", person.key + "_gps_home", person.key + "_wifi_home"):
            with self.subTest(entity=key):
                template = components[key]["value_template"]
                self.assertIn("else 'None'", template)
                self.assertIn("== 'not_home'", template)
                self.assertIn("'ON'", template)
                self.assertIn("'OFF'", template)
        self.assertEqual(
            components[person.key + "_wifi_home"]["default_entity_id"],
            "binary_sensor.dh_presence_app_" + person.key + "_wifi_home")


if __name__ == "__main__":
    unittest.main()
