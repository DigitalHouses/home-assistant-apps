"""Contract tests for the Backblaze App DH Sync 0.6.0 source."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import yaml

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "rootfs" / "app"))
from sync_discovery import SYNC_TOPIC, build_sync_payload


class BackblazeDhSyncTests(unittest.TestCase):
    def test_canonical_source_announcement(self):
        self.assertEqual(
            SYNC_TOPIC,
            "DigitalHouses/Global/digitalhouses_backblaze_app/sync",
        )
        expected = {
            "schema": 1,
            "product_id": "digitalhouses_backblaze_app",
            "type": "app",
            "version": "0.1.16",
            "repository": "https://github.com/DigitalHouses/home-assistant-apps",
            "product_path": "digitalhouses_backblaze_app",
        }
        self.assertEqual(json.loads(build_sync_payload("0.1.16")), expected)
        future = json.loads(build_sync_payload("1.2.3"))
        self.assertEqual(future["version"], "1.2.3")
        self.assertEqual(set(future), set(expected))
        for forbidden in (
            "password", "token", "username", "ip", "hostname", "bucket",
            "dashboard", "panel", "view", "order", "require_admin",
            "show_in_sidebar", "availability",
        ):
            self.assertNotIn(forbidden, future)

    def test_publish_on_each_successful_existing_mqtt_connection(self):
        app = (APP / "rootfs/app/app.py").read_text(encoding="utf-8")
        connect = app.split("    def _on_connect(", 1)[1].split(
            "    def _sync_discovery_after_connect(", 1
        )[0]
        self.assertIn("if return_code != 0:", connect)
        self.assertIn(
            "self.publish_text(SYNC_TOPIC, build_sync_payload(APP_VERSION), retain=True)",
            connect,
        )
        self.assertEqual(connect.count("build_sync_payload(APP_VERSION)"), 1)
        self.assertLess(connect.index("self.mqtt_connected.set()"),
                        connect.index("build_sync_payload(APP_VERSION)"))
        self.assertLess(connect.index("build_sync_payload(APP_VERSION)"),
                        connect.index("APP_AVAILABILITY_TOPIC"))
        self.assertIn("from sync_discovery import SYNC_TOPIC, build_sync_payload", app)
        discovery = (APP / "rootfs/app/discovery.py").read_text(encoding="utf-8")
        self.assertIn('BASE_TOPIC = "DigitalHouses/Global/backblaze"', discovery)
        self.assertIn('DEVICE_ID = "digitalhouses_backblaze"', discovery)

    def test_published_view_preserves_approved_example(self):
        canonical = yaml.safe_load(
            (APP / "dashboards/ru/backblaze.yaml").read_text(encoding="utf-8")
        )
        reference = yaml.safe_load(
            (APP / "examples/lovelace/dh_app_backblaze_dashboard.yaml").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(canonical, reference)
        self.assertEqual(canonical["title"], "Backblaze")
        self.assertEqual(canonical["path"], "backblaze")
        self.assertEqual(canonical["type"], "sections")
        self.assertNotIn("views", canonical)
        self.assertEqual(
            len(list((APP / "dashboards/ru").glob("*.yaml"))), 1
        )
        self.assertIn("sensor.dh_backblaze_storage_tree",
                      (APP / "dashboards/ru/backblaze.yaml").read_text(
                          encoding="utf-8"
                      ))
        history = [
            card
            for section in canonical["sections"]
            for card in section["cards"]
            if card.get("type") == "statistics-graph"
        ]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["days_to_show"], 30)
        self.assertEqual(history[0]["chart_type"], "bar")

    def test_published_package_keeps_recorder_identity(self):
        canonical = yaml.safe_load(
            (APP / "packages/common/dh_app_backblaze_package.yaml").read_text(
                encoding="utf-8"
            )
        )
        reference = yaml.safe_load(
            (APP / "examples/packages/dh_app_backblaze_package.yaml").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(canonical, reference)
        self.assertEqual(set(canonical), {"dh_app_backblaze_package"})
        self.assertEqual(
            canonical["dh_app_backblaze_package"]["recorder"]["include"]["entities"],
            ["sensor.dh_backblaze_storage_used", "sensor.dh_backblaze_files"],
        )
        self.assertEqual(
            len(list((APP / "packages/common").glob("*.yaml"))), 1
        )


if __name__ == "__main__":
    unittest.main()
