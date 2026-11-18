"""DH Sync v0.6.0 product declaration and canonical View contract."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import yaml

from app import Application
from zigbee_monitor import ActivityStore, ZigbeeMonitor, parse_networks
from zigbee_monitor.discovery import PRODUCT, ROOT, SYNC_TOPIC
from zigbee_monitor.service import MonitorService

APP_DIR = Path(__file__).resolve().parents[1]


class DHSyncContractTests(unittest.TestCase):
    def test_retained_identification_on_connect_and_reconnect(self):
        publications: list[tuple[str, str, bool]] = []

        def publish(topic: str, payload: str, retain: bool) -> bool:
            publications.append((topic, payload, retain))
            return True

        with tempfile.TemporaryDirectory() as temp:
            store = ActivityStore(Path(temp) / "activity.sqlite3")
            self.addCleanup(store.close)
            networks = parse_networks([{
                "network_id": "main", "name": "Main",
                "base_topic": "zigbee2mqtt",
            }])
            service = MonitorService(
                ZigbeeMonitor(networks), store,
                publish=publish, subscribe=lambda _topic: True,
                version="9.8.7",
            )
            service.connected()
            service.disconnected()
            service.connected()

            sync = [(json.loads(payload), retain)
                    for topic, payload, retain in publications
                    if topic == SYNC_TOPIC]
            self.assertEqual(SYNC_TOPIC, "DigitalHouses/Global/" + PRODUCT + "/sync")
            self.assertEqual(ROOT, "DigitalHouses/Global/dh_zigbee_monitor_app")
            self.assertEqual(len(sync), 2)
            expected = {
                "schema": 1,
                "product_id": PRODUCT,
                "type": "app",
                "version": "9.8.7",
                "repository": "https://github.com/DigitalHouses/home-assistant-apps",
                "product_path": PRODUCT,
            }
            for payload, retain in sync:
                self.assertTrue(retain)
                self.assertEqual(payload, expected)
                self.assertNotIn("dashboard", payload)
                self.assertNotIn("availability", payload)

    def test_existing_transport_uses_qos_one(self):
        recorded = []

        class MQTTClientStub:
            def publish(self, topic, payload, *, qos, retain):
                recorded.append((topic, payload, qos, retain))
                return SimpleNamespace(rc=0)

        app = Application.__new__(Application)
        app.client = MQTTClientStub()
        self.assertTrue(app._publish(SYNC_TOPIC, '{"schema":1}', True))
        self.assertEqual(recorded, [(SYNC_TOPIC, '{"schema":1}', 1, True)])

    def test_standalone_canonical_view(self):
        path = APP_DIR / "dashboards/ru/zigbee_monitor.yaml"
        view = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.assertIsInstance(view, dict)
        self.assertEqual(view["title"], "Zigbee Monitor")
        self.assertEqual(view["path"], "zigbee-monitor")
        self.assertEqual(view["type"], "sections")
        self.assertTrue(view["sections"])
        for forbidden in ("views", "dashboard", "DH-Dashboard", "DH-Order",
                          "dh_dashboard_admin_only"):
            self.assertNotIn(forbidden, view)


if __name__ == "__main__":
    unittest.main()
