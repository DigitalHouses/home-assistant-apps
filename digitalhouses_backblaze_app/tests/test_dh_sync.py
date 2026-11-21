"""Contract tests for the Backblaze App DH Sync 0.6.0 source."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "rootfs" / "app"))
from sync_discovery import SYNC_TOPIC, build_sync_payload


def meaningful_lines(path: Path) -> list[str]:
    """Compare approved YAML resources byte-for-byte except comments.

    The repository validator performs YAML parsing; runtime unit tests do not
    introduce a new PyYAML dependency into the Backblaze App build.
    """
    return [
        line for line in path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    ]


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
        canonical = APP / "dashboards/ru/backblaze.yaml"
        reference = APP / "examples/lovelace/dh_app_backblaze_dashboard.yaml"
        self.assertEqual(meaningful_lines(canonical), meaningful_lines(reference))
        view = canonical.read_text(encoding="utf-8")
        self.assertIn("\ntitle: Backblaze\npath: backblaze\n", view)
        self.assertIn("type: sections", view)
        self.assertNotIn("\nviews:", view)
        self.assertIn("sensor.dh_backblaze_storage_tree", view)
        self.assertIn("type: statistics-graph", view)
        self.assertIn("chart_type: bar", view)
        self.assertIn("days_to_show: 30", view)
        self.assertEqual(len(list((APP / "dashboards/ru").glob("*.yaml"))), 1)

    def test_published_package_keeps_recorder_identity(self):
        canonical = APP / "packages/common/dh_app_backblaze_package.yaml"
        reference = APP / "examples/packages/dh_app_backblaze_package.yaml"
        self.assertEqual(meaningful_lines(canonical), meaningful_lines(reference))
        package = canonical.read_text(encoding="utf-8")
        self.assertIn("dh_app_backblaze_package:\n", package)
        self.assertEqual(package.count("        - sensor."), 2)
        self.assertIn("sensor.dh_backblaze_storage_used", package)
        self.assertIn("sensor.dh_backblaze_files", package)
        self.assertEqual(len(list((APP / "packages/common").glob("*.yaml"))), 1)


if __name__ == "__main__":
    unittest.main()
