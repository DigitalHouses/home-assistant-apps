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
        "speedtest": {
            "periodic_enabled": True,
            "interval_minutes": 30,
            "timeout_seconds": 240,
            "server_ids": [],
            "automatic_server_fallback": True,
        },
        "traffic": {
            "traffic_download_total": "",
            "traffic_upload_total": "",
            "router_wan_status": "",
            "router_download_rate": "",
            "router_upload_rate": "",
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
        "telemetry_enabled": False,
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
        self.assertFalse(config.traffic.enabled)
        self.assertFalse(config.traffic.has_bindings)
        self.assertFalse(config.telemetry_enabled)

    def test_telemetry_is_explicit_opt_in(self) -> None:
        raw = base_options()
        raw["telemetry_enabled"] = True
        self.assertTrue(parse_options(raw).telemetry_enabled)

    def test_speedtest_server_ids_are_positive_and_deduplicated(self) -> None:
        raw = base_options()
        raw["speedtest"]["server_ids"] = [123, 456, 123]
        config = parse_options(raw)
        self.assertEqual(config.speedtest.server_ids, (123, 456))
        self.assertTrue(config.speedtest.automatic_server_fallback)
        raw["speedtest"]["server_ids"] = [0]
        with self.assertRaises(ConfigError):
            parse_options(raw)

    def test_traffic_cumulative_bindings_must_be_paired(self) -> None:
        raw = base_options()
        raw["traffic"]["traffic_download_total"] = "sensor.router_download_total"
        with self.assertRaises(ConfigError):
            parse_options(raw)

    def test_traffic_supports_five_optional_router_bindings(self) -> None:
        raw = base_options()
        raw["traffic"] = {
            "traffic_download_total": "sensor.router_download_total",
            "traffic_upload_total": "sensor.router_upload_total",
            "router_wan_status": "sensor.router_wan",
            "router_download_rate": "sensor.router_download_rate",
            "router_upload_rate": "sensor.router_upload_rate",
        }
        config = parse_options(raw)
        self.assertTrue(config.traffic.enabled)
        self.assertTrue(config.traffic.has_bindings)

    def test_traffic_sensor_domains_are_validated(self) -> None:
        raw = base_options()
        raw["traffic"]["router_download_rate"] = "input_number.rate"
        with self.assertRaises(ConfigError):
            parse_options(raw)

    def test_wan_status_accepts_sensor_or_binary_sensor(self) -> None:
        for entity_id in ("sensor.wan", "binary_sensor.wan"):
            raw = base_options()
            raw["traffic"]["router_wan_status"] = entity_id
            self.assertTrue(parse_options(raw).traffic.has_bindings)

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


if __name__ == "__main__":
    unittest.main()
