"""Contract tests for the optional Ruslan UX7 Router SNMP local source package."""

from pathlib import Path
import unittest

import yaml


PACKAGE = (
    Path(__file__).resolve().parents[1]
    / "examples/packages/dh_internet_app_router_snmp_local_package.yaml"
)


class RouterSnmpSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        content = yaml.safe_load(PACKAGE.read_text(encoding="utf-8"))
        cls.sources = content["dh_internet_app_router_snmp_local_package"]["sensor"]

    def test_two_cumulative_byte_counter_sources_only(self) -> None:
        self.assertEqual(len(self.sources), 2)
        self.assertEqual(
            {source["name"] for source in self.sources},
            {
                "dh_internet_app_router_wan_download_cumulative",
                "dh_internet_app_router_wan_upload_cumulative",
            },
        )
        self.assertEqual(
            [source["baseoid"] for source in self.sources],
            [
                "1.3.6.1.2.1.31.1.1.1.6.7",
                "1.3.6.1.2.1.31.1.1.1.10.7",
            ],
        )

    def test_local_source_has_stable_interface_and_units(self) -> None:
        for source in self.sources:
            with self.subTest(source=source["name"]):
                self.assertEqual(source["platform"], "snmp")
                self.assertEqual(source["host"], "192.168.2.1")
                self.assertEqual(source["version"], "2c")
                self.assertEqual(source["unit_of_measurement"], "B")
                self.assertEqual(source["device_class"], "data_size")
                self.assertEqual(source["scan_interval"], 60)
                self.assertTrue(source["accept_errors"])
                self.assertEqual(source["unique_id"], source["name"])
                # Cumulative statistics and month boundaries are App-owned.
                self.assertNotIn("state_class", source)


if __name__ == "__main__":
    unittest.main()
