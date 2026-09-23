from __future__ import annotations

import sys
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "rootfs" / "app"
sys.path.insert(0, str(APP_DIR))

from config import ConfigError, parse_options


def base_options() -> dict:
    return {
        "router_ip": "192.168.1.1",
        "connectivity_check": {
            "interval_seconds": 10,
            "attempts": 3,
            "timeout_seconds": 2,
        },
        "recovery": {
            "enabled": False,
            "mode": "smart",
            "max_cycles": 3,
            "retry_interval_minutes": 5,
            "boot_wait_minutes": 3,
            "cooldown_minutes": 15,
            "ont": {
                "action": "switch",
                "entity_id": "",
                "power_off_seconds": 10,
            },
            "router": {
                "action": "button",
                "entity_id": "",
                "power_off_seconds": 10,
            },
        },
        "log_level": "info",
    }


class ConfigTests(unittest.TestCase):
    def test_defaults_and_units(self) -> None:
        config = parse_options(base_options())
        self.assertEqual(config.router_ip, "192.168.1.1")
        self.assertEqual(config.recovery.mode, "smart")
        self.assertEqual(config.recovery.retry_interval_seconds, 300)
        self.assertEqual(config.recovery.boot_wait_seconds, 180)
        self.assertEqual(config.recovery.cooldown_seconds, 900)
        self.assertTrue(config.speedtest.periodic_enabled)
        self.assertEqual(config.speedtest.interval_seconds, 1800)
        self.assertEqual(config.speedtest.timeout_seconds, 240)

    def test_recovery_requires_both_targets_when_enabled(self) -> None:
        raw = base_options()
        raw["recovery"]["enabled"] = True
        with self.assertRaises(ConfigError):
            parse_options(raw)

    def test_entity_domain_must_match_action(self) -> None:
        raw = base_options()
        raw["recovery"]["ont"]["entity_id"] = "button.ont_reboot"
        with self.assertRaises(ConfigError):
            parse_options(raw)

    def test_only_smart_and_both_modes_are_supported(self) -> None:
        raw = base_options()
        raw["recovery"]["mode"] = "sequential"
        with self.assertRaises(ConfigError):
            parse_options(raw)

    def test_traffic_bindings_are_optional_but_paired(self) -> None:
        raw = base_options()
        raw["traffic"] = {
            "download_total_entity_id": "sensor.router_download_total",
            "upload_total_entity_id": "sensor.router_upload_total",
        }
        config = parse_options(raw)
        self.assertTrue(config.traffic.configured)

        raw["traffic"]["upload_total_entity_id"] = ""
        with self.assertRaises(ConfigError):
            parse_options(raw)


if __name__ == "__main__":
    unittest.main()
