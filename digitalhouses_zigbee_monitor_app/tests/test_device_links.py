"""Read-only HA Device Registry link parser regression tests."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from zigbee_monitor.device_links import load_ha_device_links

IEEE = "0x00158d0000000001"
DID = "0123456789abcdef0123456789abcdef"


class DeviceLinkTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.storage = self.root / ".storage"
        self.storage.mkdir()
        self.path = self.storage / "core.device_registry"

    def save(self, devices):
        self.path.write_text(json.dumps({
            "version": 1, "key": "core.device_registry",
            "data": {"devices": devices},
        }), encoding="utf-8")

    def read(self):
        return load_ha_device_links(self.root, is_mount=lambda _: True)

    def test_exact_mqtt_ieee_without_names(self):
        self.save([
            {"id": DID, "name_by_user": "Renamed",
             "identifiers": [["mqtt", "zigbee2mqtt_" + IEEE]]},
            {"id": "f" * 32, "identifiers": [
                ["mqtt", "other_device_" + IEEE],
            ]},
        ])
        self.assertEqual(self.read(), {IEEE: DID})

    def test_ambiguous_ieee_has_no_link(self):
        self.save([
            {"id": DID, "identifiers": [["mqtt", "zigbee2mqtt_" + IEEE]]},
            {"id": "f" * 32, "identifiers": [["mqtt", "zigbee2mqtt_" + IEEE]]},
        ])
        self.assertEqual(self.read(), {})

    def test_no_inference_from_similar_names(self):
        self.save([
            {"id": DID, "name": "zigbee2mqtt_" + IEEE,
             "identifiers": [["mqtt", "wrong-prefix_" + IEEE]]},
        ])
        self.assertEqual(self.read(), {})

    def test_missing_invalid_unmounted_and_symlink_fail_closed(self):
        self.assertEqual(self.read(), {})
        self.save([{"id": DID, "identifiers": [["mqtt", "zigbee2mqtt_" + IEEE]]}])
        self.assertEqual(load_ha_device_links(self.root, is_mount=lambda _: False), {})
        self.path.write_text("{not json", encoding="utf-8")
        self.assertEqual(self.read(), {})
        self.path.unlink()
        self.path.symlink_to(self.root / "outside")
        self.assertEqual(self.read(), {})


if __name__ == "__main__":
    unittest.main()
