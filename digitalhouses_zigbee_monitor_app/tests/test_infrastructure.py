"""Passive Z2M infrastructure tree: privacy, stable identity and persistence."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from zigbee_monitor import ActivityStore, ZigbeeMonitor, parse_networks
from zigbee_monitor.core import ZigbeeMonitorError
from zigbee_monitor.discovery import ROOT
from zigbee_monitor.infrastructure import parse_bridge_infrastructure
from zigbee_monitor.service import MonitorService

IEEE = "0x00124b002e1330dd"

def bridge_info(port="/dev/ttyUSB0", ieee=IEEE):
    return json.dumps({
        "version": "2.14.2",
        "coordinator": {"ieee_address": ieee, "type": "ZStack3x0",
                        "meta": {"revision": 20240710}},
        "config": {
            "serial": {"port": port, "adapter": "zstack", "password": "SECRET_TEST"},
            "mqtt": {"password": "SECRET_TEST"},
            "advanced": {"network_key": [1, 2, 3]},
        },
        "network": {"channel": 11, "pan_id": 8099},
        "restart_required": False,
    }).encode()

class InfrastructureTests(unittest.TestCase):
    def test_usb_allowlist(self):
        parsed = parse_bridge_infrastructure(bridge_info(), expected_ieee=IEEE)
        self.assertEqual(parsed["connection"], "usb")
        self.assertEqual(parsed["serial_port"], "/dev/ttyUSB0")
        self.assertEqual(parsed["firmware_revision"], 20240710)
        self.assertEqual(parsed["channel"], 11)
        self.assertIsNone(parsed["ip"])
        self.assertNotIn("SECRET_TEST", json.dumps(parsed))
        self.assertNotIn("network_key", json.dumps(parsed))

    def test_tcp_discovery_and_redaction(self):
        parsed = parse_bridge_infrastructure(bridge_info("tcp://192.168.1.41:6638"))
        self.assertEqual(parsed["connection"], "tcp")
        self.assertEqual(parsed["ip"], "192.168.1.41")
        parsed = parse_bridge_infrastructure(bridge_info("tcp://coordinator.local:6638"))
        self.assertEqual(parsed["network_host"], "coordinator.local")
        self.assertIsNone(parsed["ip"])
        for unsafe in (
            "tcp://user:password@192.168.1.41:6638",
            "tcp://host:6638/path", "tcp://host:6638?token=secret",
            "/dev/serial/../../etc/passwd",
        ):
            parsed = parse_bridge_infrastructure(bridge_info(unsafe))
            self.assertEqual(parsed["connection"], "unknown")
            self.assertIsNone(parsed["serial_port"])

    def test_reject_mismatch_and_invalid_info(self):
        for bad in (
            bridge_info(ieee="0x00124b002e1330de"), b"not-json", b"[]", b"{}",
        ):
            with self.subTest(bad=bad[:20]), self.assertRaises(ZigbeeMonitorError):
                parse_bridge_infrastructure(bad, expected_ieee=IEEE)

    def test_storage_upgrade_and_multi_network_presentation(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "activity.sqlite"
            with ActivityStore(path) as store:
                network, _ = store.register_network(IEEE, "zigbee2mqtt", observed_at=1)
                published = []
                service = MonitorService(
                    ZigbeeMonitor(parse_networks([
                        {"network_id": network.network_id, "base_topic": "zigbee2mqtt",
                         "name": "zigbee2mqtt"},
                        {"network_id": "other", "base_topic": "z2m_other",
                         "name": "Other"},
                    ])),
                    store, version="0.1.9",
                    publish=lambda topic,body,retained: published.append((topic,body)) or True,
                    subscribe=lambda _: True,
                    now=lambda: 1000.0,
                )
                service.connected()
                self.assertEqual(
                    service.receive("zigbee2mqtt/bridge/info", bridge_info(), retain=True),
                    "bridge_info",
                )
                rows = [json.loads(body)["networks"] for topic,body in published
                        if topic == ROOT + "/state/networks_details"]
                self.assertEqual(len(rows[-1]), 2)
                by_id = {r["network_id"]: r for r in rows[-1]}
                self.assertTrue(by_id[network.network_id]["infrastructure_seen"])
                self.assertEqual(by_id[network.network_id]["infrastructure"]["connection"], "usb")
                self.assertIsNone(by_id["other"]["infrastructure"])
                self.assertFalse(by_id["other"]["infrastructure_seen"])
                self.assertIn("bridge_offline", by_id[network.network_id]["problem_unknown"])
                with self.assertRaises(ZigbeeMonitorError):
                    service.receive("zigbee2mqtt/bridge/info",
                                    bridge_info(ieee="0x00124b002e1330de"))
                service.disconnected()
            with ActivityStore(path) as store:
                persisted = store.network_infrastructure(network.network_id)
                self.assertEqual(persisted["data"]["coordinator_ieee"], IEEE)
                self.assertEqual(persisted["data"]["z2m_version"], "2.14.2")
                self.assertNotIn("SECRET_TEST", json.dumps(persisted))

if __name__ == "__main__":
    unittest.main()
