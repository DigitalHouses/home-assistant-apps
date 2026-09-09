import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tempfile import TemporaryDirectory
import unittest

from app.config import load_config
from app.discovery import build_discovery_payload, build_topics
from app.models import BuildInfo


class DiscoveryTests(unittest.TestCase):
    def config(self, instance="plex"):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "app.conf"
        path.write_text(
            f"[general]\ninstance_id = {instance}\n"
            f"instance_name = DH Plex\n"
            "[mqtt]\nhost = mqtt\n",
            encoding="utf-8",
        )
        return load_config(path)

    def test_default_topics(self):
        topics = build_topics(self.config())
        self.assertEqual(
            topics.state,
            "DigitalHouses/Global/plex_monitoring/state",
        )
        self.assertEqual(
            topics.discovery,
            "homeassistant/device/digitalhouses_plex_monitoring_plex/config",
        )

    def test_default_entity_ids(self):
        payload = build_discovery_payload(
            self.config(),
            BuildInfo("0.1.0", "main", "abcdef1234567890"),
        )
        components = payload["components"]
        expected = {
            "activity": "sensor.dh_plex_activity",
            "cpu": "sensor.dh_plex_cpu",
            "credits_detection": "binary_sensor.dh_plex_credits_detection",
            "refresh": "button.dh_plex_refresh",
        }
        for key, entity_id in expected.items():
            self.assertEqual(
                components[key]["default_entity_id"],
                entity_id,
            )

    def test_second_instance_entity_ids(self):
        payload = build_discovery_payload(
            self.config("plex_guest"),
            BuildInfo("0.1.0", "main", "abcdef"),
        )
        components = payload["components"]
        topics = build_topics(self.config("plex_guest"))
        self.assertEqual(
            topics.state,
            "DigitalHouses/Global/plex_monitoring/plex_guest/state",
        )
        self.assertEqual(
            components["activity"]["default_entity_id"],
            "sensor.dh_plex_guest_activity",
        )
        self.assertEqual(
            components["refresh"]["default_entity_id"],
            "button.dh_plex_guest_refresh",
        )

    def test_process_entities_have_dual_availability(self):
        payload = build_discovery_payload(
            self.config(),
            BuildInfo("0.1.0", "main", "abcdef"),
        )
        components = payload["components"]
        self.assertEqual(len(components["cpu"]["availability"]), 2)
        self.assertEqual(
            len(components["collector_status"]["availability"]),
            1,
        )
        self.assertEqual(len(components["refresh"]["availability"]), 1)


if __name__ == "__main__":
    unittest.main()
