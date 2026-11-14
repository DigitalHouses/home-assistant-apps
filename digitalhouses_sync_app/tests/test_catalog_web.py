"""The installed v0.1.0 HTTP surface is GET-only and independent of HA APIs."""
from __future__ import annotations

import http.client
import tempfile
import threading
import unittest
from pathlib import Path

from catalog_web import make_server
from discovery_contract import ProductSources
from inventory import Inventory


def fetch(server, method="GET", path="/"):
    conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
    try:
        conn.request(method, path)
        response = conn.getresponse()
        return response.status, response.read().decode("utf-8")
    finally:
        conn.close()


class CatalogTests(unittest.TestCase):
    def test_catalog_renders_live_mqtt_payloads_and_rejects_post(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = ProductSources(root / "sources.json")
            inventory = Inventory(root / "inventory.json")
            # Synthetic instance ID; never publish real home machine identifiers.
            pve = "DigitalHouses/Global/digitalhouses_pve_agent/0123456789abcdef0123456789abcdef/sync"
            plex = "DigitalHouses/Global/digitalhouses_plex_agent/sync"
            repo = "https://github.com/DigitalHouses/home-assistant-apps"
            import json
            for topic, product, version in (
                (pve, "digitalhouses_pve_agent", "0.5.89"),
                (plex, "digitalhouses_plex_agent", "0.8.18"),
            ):
                sources.apply(topic, json.dumps({
                    "schema": 1, "product_id": product, "type": "agent",
                    "version": version, "repository": repo, "product_path": product,
                }))
            inventory.apply(
                pve.removesuffix("/sync") + "/availability", "online")
            inventory.apply(
                plex.removesuffix("/sync") + "/availability", "online")
            server = make_server(sources, inventory, version="0.1.2", port=0)
            server.timeout = 2
            thread = threading.Thread(
                target=lambda: [server.handle_request() for _ in range(2)],
                daemon=True,
            )
            try:
                thread.start()
                status, body = fetch(server)
                self.assertEqual(status, 200)
                for expected in (
                    "digitalhouses_pve_agent", "digitalhouses_plex_agent",
                    "0.5.89", "0.8.18", "Online",
                    "home-assistant-apps", "0123456789abcdef0123456789abcdef",
                    "DigitalHouses Sync · v0.1.2",
                ):
                    self.assertIn(expected, body)
                self.assertNotIn("<form", body)
                self.assertNotIn("Применить", body)
                self.assertEqual(fetch(server, "POST")[0], 405)
            finally:
                server.server_close()
                thread.join(timeout=4)

    def test_self_availability_is_online_in_catalog(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = ProductSources(root / "sources.json")
            inventory = Inventory(root / "inventory.json")
            sources.apply(
                "DigitalHouses/Global/digitalhouses_sync_app/sync",
                json.dumps({
                    "schema": 1, "product_id": "digitalhouses_sync_app",
                    "type": "app", "version": "0.1.2",
                    "repository": "https://github.com/DigitalHouses/home-assistant-apps",
                    "product_path": "digitalhouses_sync_app"
                }),
            )
            self.assertTrue(inventory.apply(
                "DigitalHouses/Global/digitalhouses_sync_app/availability",
                "online",
            ))
            server = make_server(sources, inventory, version="0.1.2", port=0)
            server.timeout = 2
            thread = threading.Thread(target=server.handle_request, daemon=True)
            try:
                thread.start()
                status, body = fetch(server)
                self.assertEqual(status, 200)
                self.assertIn("digitalhouses_sync_app", body)
                self.assertIn("DigitalHouses Sync · v0.1.2", body)
                self.assertIn("Online", body)
                self.assertNotIn("Unknown</span>", body)
            finally:
                server.server_close()
                thread.join(timeout=3)

    def test_version_header_escapes_text(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            server = make_server(
                ProductSources(root / "sources.json"),
                Inventory(root / "inventory.json"),
                version="<script>alert(1)</script>", port=0,
            )
            server.timeout = 2
            thread = threading.Thread(target=server.handle_request, daemon=True)
            try:
                thread.start()
                status, body = fetch(server)
                self.assertEqual(status, 200)
                self.assertNotIn("<script>", body)
                self.assertIn("&lt;script&gt;", body)
            finally:
                server.server_close()
                thread.join(timeout=3)

    def test_empty_catalog_does_not_claim_products_are_absent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            server = make_server(
                ProductSources(root / "none.json"),
                Inventory(root / "unknown.json"), port=0,
            )
            server.timeout = 2
            thread = threading.Thread(target=server.handle_request, daemon=True)
            try:
                thread.start()
                status, body = fetch(server)
                self.assertEqual(status, 200)
                self.assertIn("пока не обнаружены", body)
            finally:
                server.server_close()
                thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
