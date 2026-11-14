"""The automatic sync Ingress lists dashboards and packages separately."""
from __future__ import annotations

import threading
import unittest
from http.client import HTTPConnection

from catalog_web import make_server


class Sources:
    def snapshot(self):
        return {
            "example/default": {
                "product_id": "example", "version": "1.0.0",
                "type": "app", "repository": "https://github.com/DigitalHouses/example",
                "product_path": "example",
            },
        }


class Inventory:
    known = {"example/default": "online"}


class AutoStatusUiTests(unittest.TestCase):
    def test_two_resource_sections_and_local_paths(self):
        status = {
            "state": "OK", "updated": 2, "unchanged": 1,
            "last_run": "2026-11-14T07:00:00+00:00", "issues": [],
            "resources": [
                {"name": "example / 10_dashboard.yaml", "kind": "view",
                 "local_path": "/config/dashboards/dh/views/10_dashboard.yaml",
                 "status": "Updated"},
                {"name": "example / dh_example_package.yaml", "kind": "package",
                 "local_path": "/config/packages/Global/dh_example_package.yaml",
                 "status": "Current"},
                {"name": "example / other.yaml", "kind": "package",
                 "local_path": "", "status": "Skipped: duplicate key"},
            ],
        }
        server = make_server(Sources(), Inventory(), port=0,
                             version="0.4.1", auto_status=lambda: status)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            connection = HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            connection.request("GET", "/")
            result = connection.getresponse()
            html = result.read().decode()
            self.assertEqual(result.status, 200)
            self.assertIn("Dashboards (1)", html)
            self.assertIn("Packages (2)", html)
            self.assertIn("/config/dashboards/dh/views/10_dashboard.yaml", html)
            self.assertIn("/config/packages/Global/dh_example_package.yaml", html)
            self.assertIn("Skipped: duplicate key", html)
            self.assertIn("<code>—</code>", html)
            self.assertNotIn("Подтверждаю", html)
            self.assertNotIn("Применить", html)
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
