"""Regression for the live CORE MQTT /sync shapes observed 2026-11-14.

The real PVE instance identifier is deliberately anonymized. These are
contract-shaped fixtures, NOT a claim that CI is subscribed to a live broker.
"""
from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from discovery_contract import ProductSources
from sync_engine import SyncError
from sync_web import make_server

PVE_TOPIC = (
    "DigitalHouses/Global/digitalhouses_pve_agent/"
    "0123456789abcdef0123456789abcdef/sync"
)
PLEX_TOPIC = "DigitalHouses/Global/digitalhouses_plex_agent/sync"
REPO = "https://github.com/DigitalHouses/home-assistant-apps"

# PVE and Plex intentionally serialize fields in different order.
PVE_MESSAGE = (
    '{"schema":1,"product_id":"digitalhouses_pve_agent","type":"agent",'
    '"version":"0.5.89","repository":"https://github.com/DigitalHouses/home-assistant-apps",'
    '"product_path":"digitalhouses_pve_agent"}'
)
PLEX_MESSAGE = (
    '{"product_id":"digitalhouses_plex_agent",'
    '"product_path":"digitalhouses_plex_agent",'
    '"repository":"https://github.com/DigitalHouses/home-assistant-apps",'
    '"schema":1,"type":"agent","version":"0.8.18"}'
)


class SourceFixtures(unittest.TestCase):
    def test_both_live_payload_shapes_are_accepted_and_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "product_sources.json"
            sources = ProductSources(path)
            self.assertTrue(sources.apply(PVE_TOPIC, PVE_MESSAGE.encode()))
            self.assertTrue(sources.apply(PLEX_TOPIC, PLEX_MESSAGE.encode()))
            self.assertFalse(sources.apply(PLEX_TOPIC, PLEX_MESSAGE.encode()))
            sources.save()
            sources = ProductSources(path)
            records = sources.snapshot()
            self.assertEqual(len(records), 2)
            self.assertEqual(
                records["digitalhouses_pve_agent/0123456789abcdef0123456789abcdef"]["version"],
                "0.5.89",
            )
            self.assertEqual(records["digitalhouses_plex_agent/default"]["version"], "0.8.18")
            self.assertEqual({x["repository"] for x in records.values()}, {REPO})
            self.assertEqual(
                {x["product_path"] for x in records.values()},
                {"digitalhouses_pve_agent", "digitalhouses_plex_agent"},
            )

    def test_catalog_remains_visible_when_yaml_apply_is_incompatible(self):
        class IncompatibleEngine:
            def __init__(self):
                self.applies = 0

            def plan(self):
                return {
                    "blocked": True,
                    "changes": 0,
                    "fingerprint": "a" * 64,
                    "items": [
                        {"title": "Proxmox", "path": "10_pve_proxmox.yaml",
                         "installed_agent": "0.5.89", "required_agent": "0.5.88",
                         "action": "incompatible", "source_commit": "a" * 40},
                        {"title": "Plex", "path": "12_plex.yaml",
                         "installed_agent": "0.8.18", "required_agent": "0.8.17",
                         "action": "incompatible", "source_commit": "b" * 40},
                    ],
                }

            def last_transaction(self):
                return None

            def apply(self, fingerprint, *, approved):
                self.applies += 1
                raise SyncError("Cannot apply on newer agent")

        with tempfile.TemporaryDirectory() as directory:
            sources = ProductSources(Path(directory) / "product_sources.json")
            sources.apply(PVE_TOPIC, PVE_MESSAGE)
            sources.apply(PLEX_TOPIC, PLEX_MESSAGE)
            engine = IncompatibleEngine()
            # Constructor binds only a private ephemeral port for the test.
            server = make_server(engine, allow_changes=False, port=0, sources=sources)
            thread = threading.Thread(target=server.handle_request, daemon=True)
            try:
                thread.start()
                conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
                try:
                    conn.request("GET", "/")
                    response = conn.getresponse()
                    body = response.read().decode("utf-8")
                    self.assertEqual(response.status, 200)
                finally:
                    conn.close()
                for word in (
                    "Найденные продукты", "digitalhouses_pve_agent",
                    "digitalhouses_plex_agent", "0.5.89", "0.8.18", REPO,
                    "Версия не подтверждена", "Только просмотр",
                ):
                    self.assertIn(word, body)
                self.assertEqual(engine.applies, 0)
                self.assertIn('disabled', body)
            finally:
                server.server_close()
                thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
