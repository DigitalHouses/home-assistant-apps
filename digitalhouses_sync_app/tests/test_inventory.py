import json
import tempfile
import unittest
from pathlib import Path

from inventory import Inventory, parse_availability


class InventoryTest(unittest.TestCase):
    def test_existing_pve_namespace(self):
        self.assertEqual(
            parse_availability("DigitalHouses/Global/digitalhouses_pve_agent/abc/availability"),
            ("digitalhouses_pve_agent", "abc"),
        )

    def test_existing_app_namespace(self):
        self.assertEqual(
            parse_availability("DigitalHouses/Global/dh_network_app/availability"),
            ("digitalhouses_network_app", "default"),
        )

    def test_no_secondary_availability(self):
        self.assertIsNone(
            parse_availability("DigitalHouses/Global/backblaze/data_availability")
        )

    def test_offline_never_installs_or_uninstalls(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / "inventory.json"
            inventory = Inventory(path)
            topic = "DigitalHouses/Global/digitalhouses_pve_agent/abc/availability"
            self.assertFalse(inventory.apply(topic, "offline"))
            self.assertTrue(inventory.apply(topic, "online"))
            self.assertTrue(inventory.apply(topic, "offline"))
            inventory.save()
            self.assertEqual(
                Inventory(path).known["digitalhouses_pve_agent/abc"], "offline"
            )

    def test_sync_app_self_availability_topic(self):
        topic = "DigitalHouses/Global/digitalhouses_sync_app/availability"
        self.assertEqual(parse_availability(topic), ("digitalhouses_sync_app", "default"))
        with tempfile.TemporaryDirectory() as t:
            inventory = Inventory(Path(t) / "inventory.json")
            self.assertTrue(inventory.apply(topic, "online"))
            self.assertEqual(inventory.known["digitalhouses_sync_app/default"], "online")
            self.assertTrue(inventory.apply(topic, "offline"))
            # Never remove a discovered product when it goes offline.
            self.assertEqual(inventory.known["digitalhouses_sync_app/default"], "offline")

    def test_unknown_topic_is_ignored(self):
        with tempfile.TemporaryDirectory() as t:
            inventory = Inventory(Path(t) / "inventory.json")
            self.assertFalse(
                inventory.apply("DigitalHouses/Global/unknown/availability", "online")
            )


if __name__ == "__main__":
    unittest.main()

