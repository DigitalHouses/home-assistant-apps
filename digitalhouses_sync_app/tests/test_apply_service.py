"""DH Sync 0.3 explicit Apply/Rollback regression cases."""
from __future__ import annotations

import hashlib
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from http.client import HTTPConnection
from urllib.parse import urlencode

from apply_service import ApplyError, ApplyManager
from catalog_web import make_server
from discovery_contract import ProductSources
from inventory import Inventory
from resource_preview import MissingDirectory, list_views, PreviewCatalog

REPO = "https://github.com/DigitalHouses/any-repo"
SHA = "e" * 40
PRODUCT = "third_party_app"
IDENTITY = PRODUCT + "/default"


def view(title: str, path: str, extra: str = "") -> bytes:
    return (f"title: {title}\npath: {path}\ntype: sections\n"
            "sections:\n  - type: grid\n    cards: []\n" + extra).encode()


class FakeCatalog:
    def __init__(self, views):
        self.views = views

    def inspect(self, claims):
        claim = next(iter(claims.values()))
        return [{
            "identity": IDENTITY, "product": PRODUCT, "version": claim["version"],
            "repository": claim["repository"], "product_path": "dash",
            "commit": SHA, "label": "DigitalHouses · main",
            "error": "", "views": [
                {"file": filename, "path": path, "title": title, "revision": "—"}
                for filename, path, title in self.views
            ],
        }]


class ApplyServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.root = base / "ha"
        self.views = self.root / "dashboards/dh/views"
        self.views.mkdir(parents=True)
        (self.root / "dashboards/dh/ui.yaml").write_text(
            "title: DigitalHouses\nviews: !include_dir_list views/\n")
        (self.root / ".storage").mkdir()
        self.data = base / "backup"
        self.old = view("Old view", "first")
        self.new = view("New view", "first")
        self.other = view("Second view", "second")
        self.sources = {
            "dash/dashboards/ru/10_first.yaml": self.new,
            "dash/dashboards/ru/11_second.yaml": self.other,
        }
        self.manager = ApplyManager(
            self.root, self.data,
            catalog=FakeCatalog([
                ("10_first.yaml", "first", "New view"),
                ("11_second.yaml", "second", "Second view"),
            ]),
            fetcher=lambda repo, path, sha: self.sources[path],
        )
        self.claims = {IDENTITY: {
            "product_id": PRODUCT, "version": "999.999.999",
            "repository": REPO, "product_path": "dash",
        }}

    def test_missing_views_create_and_rollback_without_other_files(self):
        unrelated = self.views / "99_personal.yaml"
        unrelated.write_bytes(view("Personal", "personal"))
        before = unrelated.read_bytes()
        plan = self.manager.prepare(self.claims, IDENTITY)
        self.assertEqual(plan["changes"], 2)
        self.assertEqual(plan["commit"], SHA)
        self.assertEqual([e["action"] for e in plan["entries"]], ["create", "create"])
        result = self.manager.apply(plan["token"], confirmed=True)
        self.assertEqual(result["count"], 2)
        self.assertEqual((self.views / "10_first.yaml").read_bytes(), self.new)
        self.assertEqual(unrelated.read_bytes(), before)
        manifest = self.manager.last_transaction()
        self.assertIsNotNone(manifest)
        self.assertEqual(manifest["state"], "applied")
        token = self.manager.rollback_preview()["token"]
        self.assertEqual(self.manager.rollback(token, confirmed=True)["count"], 2)
        self.assertFalse((self.views / "10_first.yaml").exists())
        self.assertFalse((self.views / "11_second.yaml").exists())
        self.assertEqual(unrelated.read_bytes(), before)

    def test_existing_modified_view_restore_exact_bytes(self):
        path = self.views / "10_first.yaml"
        path.write_bytes(self.old)
        plan = self.manager.prepare(self.claims, IDENTITY)
        self.assertEqual(plan["entries"][0]["action"], "replace")
        self.manager.apply(plan["token"], confirmed=True)
        self.assertEqual(path.read_bytes(), self.new)
        self.manager.rollback(self.manager.rollback_preview()["token"], confirmed=True)
        self.assertEqual(path.read_bytes(), self.old)

    def test_stale_plan_rejected_before_any_write(self):
        path = self.views / "10_first.yaml"
        path.write_bytes(self.old)
        plan = self.manager.prepare(self.claims, IDENTITY)
        custom = view("User changed this", "first")
        path.write_bytes(custom)
        with self.assertRaisesRegex(ApplyError, "changed since preview"):
            self.manager.apply(plan["token"], confirmed=True)
        self.assertEqual(path.read_bytes(), custom)
        self.assertFalse((self.views / "11_second.yaml").exists())

    def test_storage_collision_blocks_entire_product(self):
        item = {"data": {"config": {"views": [{"path": "second"}]}}}
        (self.root / ".storage" / "lovelace").write_text(json.dumps(item))
        with self.assertRaisesRegex(ApplyError, "Storage"):
            self.manager.prepare(self.claims, IDENTITY)
        self.assertFalse((self.views / "10_first.yaml").exists())

    def test_rejects_unowned_repository_without_fetch(self):
        self.claims[IDENTITY]["repository"] = "https://github.com/EvilOrg/any-repo"
        with self.assertRaises(ValueError):
            self.manager.prepare(self.claims, IDENTITY)

    def test_refuse_rollback_if_user_edited_new_yaml(self):
        p = self.manager.prepare(self.claims, IDENTITY)
        self.manager.apply(p["token"], confirmed=True)
        target = self.views / "10_first.yaml"
        custom = view("Edited after Apply", "first")
        target.write_bytes(custom)
        with self.assertRaisesRegex(ApplyError, "changed after Apply"):
            self.manager.rollback(self.manager.rollback_preview()["token"],
                                  confirmed=True)
        self.assertEqual(target.read_bytes(), custom)
        self.assertTrue((self.views / "11_second.yaml").exists())

    def test_single_use_confirmation_and_expiry(self):
        p = self.manager.prepare(self.claims, IDENTITY)
        with self.assertRaisesRegex(ApplyError, "confirmation"):
            self.manager.apply(p["token"], confirmed=False)
        # A declined action does not consume the token.
        result = self.manager.apply(p["token"], confirmed=True)
        self.assertEqual(result["status"], "applied")
        with self.assertRaisesRegex(ApplyError, "already used"):
            self.manager.apply(p["token"], confirmed=True)
        p2 = self.manager.prepare(self.claims, IDENTITY)
        with patch.object(self.manager, "clock", return_value=999999999):
            with self.assertRaisesRegex(ApplyError, "expired"):
                self.manager.apply(p2["token"], confirmed=True)

    def test_symlink_destination_is_rejected(self):
        elsewhere = Path(self.tmp.name) / "outside.yaml"
        elsewhere.write_bytes(self.old)
        (self.views / "10_first.yaml").symlink_to(elsewhere)
        with self.assertRaises(ValueError):
            self.manager.prepare(self.claims, IDENTITY)
        self.assertEqual(elsewhere.read_bytes(), self.old)

    def test_no_published_directory_is_normal_absence(self):
        with patch("resource_preview._download", side_effect=MissingDirectory("absent")):
            self.assertEqual(list_views(REPO, "dash", SHA), [])


class IngressTests(unittest.TestCase):
    def test_plan_requires_confirmation_and_writes_only_on_post(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "ha"
            views = root / "dashboards/dh/views"
            views.mkdir(parents=True)
            (root / "dashboards/dh/ui.yaml").write_text(
                "title: DigitalHouses\nviews: !include_dir_list views/\n")
            (root / ".storage").mkdir()
            source = view("Recorder", "recorder")
            repo = "https://github.com/DigitalHouses/home-assistant-apps"
            claim = {"product_id": "digitalhouses_recorder_app",
                     "repository": repo, "product_path": "digitalhouses_recorder_app",
                     "type": "app", "version": "0.1.29"}
            sources = ProductSources(Path(folder) / "sources.json")
            sources.apply("DigitalHouses/Global/digitalhouses_recorder_app/sync",
                          json.dumps(claim).encode())
            inventory = Inventory(Path(folder) / "inventory.json")
            manager = ApplyManager(
                root, Path(folder) / "backup",
                catalog=FakeCatalog([("10_first.yaml", "recorder", "Recorder")]),
                fetcher=lambda repo, path, sha: source,
            )
            # FakeCatalog returns arbitrary product identity, but the accepted
            # GitHub source and requested MQTT identity remain unchanged.
            original = manager.catalog.inspect
            def with_real_identity(c):
                result = original(c)
                result[0]["identity"] = "digitalhouses_recorder_app/default"
                result[0]["product"] = "digitalhouses_recorder_app"
                return result
            manager.catalog.inspect = with_real_identity
            server = make_server(sources, inventory, port=0,
                                 version="0.3.0", apply_manager=manager)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                http = HTTPConnection("127.0.0.1", port, timeout=10)
                http.request("GET", "/?plan=digitalhouses_recorder_app%2Fdefault")
                response = http.getresponse()
                html = response.read().decode()
                self.assertEqual(response.status, 200)
                self.assertIn("Предпросмотр Apply", html)
                self.assertFalse((views / "10_first.yaml").exists())
                token = html.split("name='token' value='")[1].split("'")[0]
                http.request("POST", "/", urlencode({
                    "op": "apply", "token": token, "confirm": "YES",
                }), {"Content-Type": "application/x-www-form-urlencoded"})
                response = http.getresponse()
                self.assertEqual(response.status, 200)
                self.assertIn("applied", response.read().decode())
                self.assertEqual((views / "10_first.yaml").read_bytes(), source)
                http.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
