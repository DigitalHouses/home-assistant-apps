"""Regression coverage for the Recorder App DH Sync Discovery v1 contract."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from urllib.parse import urlsplit

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "rootfs" / "app"))

from discovery import (  # noqa: E402
    APP_AVAILABILITY_TOPIC,
    DEVICE_ID,
    DISCOVERY_TOPIC,
    build_discovery_payload,
)
from sync_discovery import (  # noqa: E402
    PRODUCT_PATH,
    REPOSITORY_URL,
    SYNC_TOPIC,
    build_sync_payload,
)


class SyncDiscoveryContractTests(unittest.TestCase):
    def test_exact_contract_and_canonical_topic(self):
        version = "0.1.28"
        payload = build_sync_payload(version)
        self.assertEqual(
            SYNC_TOPIC,
            "DigitalHouses/Global/digitalhouses_recorder_app/sync",
        )
        self.assertEqual(payload, {
            "schema": 1,
            "product_id": "digitalhouses_recorder_app",
            "type": "app",
            "version": version,
            "repository": "https://github.com/DigitalHouses/home-assistant-apps",
            "product_path": "digitalhouses_recorder_app",
        })
        self.assertIs(type(payload["schema"]), int)

    def test_running_version_matches_ha_discovery(self):
        version = "0.1.28"
        sync_payload = build_sync_payload(version)
        discovery_payload = build_discovery_payload(version)
        self.assertEqual(
            sync_payload["version"], discovery_payload["device"]["sw_version"]
        )
        self.assertEqual(
            sync_payload["version"], discovery_payload["origin"]["sw_version"]
        )

    def test_same_released_mqtt_identity(self):
        self.assertEqual(DEVICE_ID, "digitalhouses_recorder_app")
        self.assertEqual(
            DISCOVERY_TOPIC,
            "homeassistant/device/digitalhouses_recorder_app/config",
        )
        self.assertEqual(
            APP_AVAILABILITY_TOPIC,
            "DigitalHouses/Global/digitalhouses_recorder_app/availability",
        )

    def test_bad_versions_rejected(self):
        for version in ("", "latest", "v0.1.28", "0.1", "0.1.28-rc.1", None):
            with self.subTest(version=version):
                with self.assertRaises(ValueError):
                    build_sync_payload(version)

    def test_repository_url_is_fixed_and_owned_by_digitalhouses(self):
        parsed = urlsplit(REPOSITORY_URL)
        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.hostname, "github.com")
        self.assertEqual(parsed.netloc, "github.com")
        self.assertEqual(parsed.path, "/DigitalHouses/home-assistant-apps")
        self.assertFalse(parsed.query or parsed.fragment or parsed.username)
        self.assertEqual(PRODUCT_PATH, "digitalhouses_recorder_app")

    def test_ru_view_is_standalone_and_preserves_existing_dashboard(self):
        canonical = (APP / "dashboards" / "ru" / "10_recorder.yaml").read_text(
            encoding="utf-8"
        )
        maintained = (APP / "examples" / "lovelace" /
                      "dh_recorder_app_dashboard.yaml").read_text(encoding="utf-8")
        self.assertTrue(canonical.startswith(
            "# DH-View: dh_recorder_app\n"
            "# DH-View-Version: 1.0.0\n"
            "# DH-View-Date: 2026-11-14\n"
        ))
        self.assertIn("\ntitle: DH Recorder\npath: recorder\nicon: mdi:database\n"
                      "type: sections\n", canonical)
        self.assertEqual(
            canonical.split("title: DH Recorder", 1)[1],
            maintained.split("title: DH Recorder", 1)[1],
        )
        self.assertNotIn("lovelace:", canonical)
        self.assertNotIn("192.168.", canonical)


if __name__ == "__main__":
    unittest.main()
