"""DH Sync 0.6.0 announcement and canonical resource regression tests."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "rootfs" / "app"))
from sync_discovery import SYNC_TOPIC, build_sync_payload


class DhSyncTests(unittest.TestCase):
    def test_canonical_source_payload(self):
        self.assertEqual(SYNC_TOPIC, "DigitalHouses/Global/digitalhouses_internet_app/sync")
        expected = {
            "schema": 1,
            "product_id": "digitalhouses_internet_app",
            "type": "app",
            "version": "0.1.26",
            "repository": "https://github.com/DigitalHouses/home-assistant-apps",
            "product_path": "digitalhouses_internet_app",
        }
        self.assertEqual(json.loads(build_sync_payload("0.1.26")), expected)
        updated = json.loads(build_sync_payload("1.2.3"))
        self.assertEqual(updated["version"], "1.2.3")
        self.assertEqual(set(updated), set(expected))
        for forbidden in (
            "password", "token", "username", "ip", "hostname", "customer",
            "dashboard", "panel", "view", "order", "require_admin",
            "show_in_sidebar",
        ):
            self.assertNotIn(forbidden, updated)

    def test_publish_on_every_successful_mqtt_connection(self):
        app = (APP / "rootfs" / "app" / "app.py").read_text(encoding="utf-8")
        connect = app.split("    def _on_connect(", 1)[1].split("    def _on_message(", 1)[0]
        self.assertIn("if reason_code != 0:", connect)
        self.assertIn("from sync_discovery import SYNC_TOPIC, build_sync_payload", app)
        announcement = "client.publish(\\n            SYNC_TOPIC, build_sync_payload(APP_VERSION), qos=1, retain=True\\n        )"
        # One retained source publish inside on_connect; no timer/polling is required.
        self.assertEqual(connect.count(announcement.replace("\\n", "\n")), 1)
        self.assertLess(connect.index("SYNC_TOPIC"), connect.index("DISCOVERY_TOPIC"))
        self.assertLess(connect.index("SYNC_TOPIC"), connect.index('TOPICS["availability"]'))
        self.assertIn('MQTT_BASE_TOPIC = "DigitalHouses/Global/dh_internet_app"',
                      (APP / "rootfs" / "app" / "discovery.py").read_text(encoding="utf-8"))

    def test_canonical_ru_resources_reuse_approved_examples(self):
        pairs = (
            ("dashboards/ru/13_internet.yaml",
             "examples/lovelace/dh_internet_app_dashboard.yaml"),
            ("packages/common/dh_internet_app_global_package.yaml",
             "examples/packages/dh_internet_app_global_package.yaml"),
            ("packages/locales/ru/dh_internet_app_notification_local_package.yaml",
             "examples/packages/locales/ru/dh_internet_app_notification_local_package.yaml"),
        )
        def normalize(value):
            return "\n".join(line for line in value.splitlines()
                             if not line.startswith("#")).strip()
        for published, example in pairs:
            with self.subTest(published=published):
                text = (APP / published).read_text(encoding="utf-8")
                reference = (APP / example).read_text(encoding="utf-8")
                self.assertEqual(normalize(text), normalize(reference))
                self.assertNotIn("script.write2log", text)
        view = (APP / pairs[0][0]).read_text(encoding="utf-8")
        self.assertIn("title: Internet\npath: internet\nicon: mdi:web\ntype: sections", view)
        self.assertNotIn("\nviews:", view)
        recorder = (APP / pairs[1][0]).read_text(encoding="utf-8")
        notify = (APP / pairs[2][0]).read_text(encoding="utf-8")
        self.assertIn("dh_internet_app_global_package:\n", recorder)
        self.assertIn("dh_internet_app_notification_local_package:\n", notify)
        self.assertIn("persistent_notification.create", notify)
        self.assertIn("event.dh_internet_app_event", notify)
        self.assertEqual(list((APP / "dashboards" / "ru").glob("*.yaml")).__len__(), 1)
        self.assertEqual(list((APP / "packages" / "common").glob("*.yaml")).__len__(), 1)
        self.assertEqual(list((APP / "packages" / "locales" / "ru").glob("*.yaml")).__len__(), 1)


    def test_english_resources_preserve_canonical_contract(self):
        import re

        ru = (APP / "dashboards/ru/13_internet.yaml").read_text(encoding="utf-8")
        en = (APP / "dashboards/en/13_internet.yaml").read_text(encoding="utf-8")
        self.assertNotRegex(en, r"[А-Яа-яЁё]")
        self.assertIn("title: Internet\npath: internet\nicon: mdi:web\ntype: sections", en)
        for pattern in (
            r"\b(?:sensor|binary_sensor|button|number|event|update)\.[a-z0-9_]+",
            r"(?m)^\s*(?:- )?type: [^\n]+",
            r"(?m)^\s*perform_action: [^\n]+",
        ):
            self.assertEqual(re.findall(pattern, ru), re.findall(pattern, en))
        en_notify = (APP / "packages/locales/en/dh_internet_app_notification_local_package.yaml").read_text(encoding="utf-8")
        en_example = (APP / "examples/packages/dh_internet_app_notification_local_package.yaml").read_text(encoding="utf-8")
        self.assertEqual(en_notify, en_example)
        self.assertNotIn("speedtest_failed", en_notify)


if __name__ == "__main__":
    unittest.main()
