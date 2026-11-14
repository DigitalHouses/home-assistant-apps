"""DH Sync v0.2 local config audit: exact, semantic, divergent and Storage cases."""
from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from catalog_web import make_server
from discovery_contract import ProductSources
from inventory import Inventory
from local_audit import LocalAuditor
from test_catalog_web import fetch

REPO = "https://github.com/DigitalHouses/home-assistant-apps"
PVE = "digitalhouses_pve_agent"
PLEX = "digitalhouses_plex_agent"
COMMITS = {PVE: "7a2bc76f7c69312366ea70a6d9236549a978d636",
        PLEX: "fd9d257972f0afdf979bfdd27ba7c6c86991fceb"}


def yaml_view(product, title, path, *, extra=""):
    return (f"# DH-View: dh_{product.removeprefix('digitalhouses_')}\n"
            "# DH-View-Version: 1.0.0\n"
            "\n"
            f"title: {title}\npath: {path}\ntype: sections\nsections: []\n" + extra).encode()


def entry(product, views):
    return {"product": product, "repository": REPO, "product_path": product,
            "version": "0.5.89" if product == PVE else "0.8.18",
            "commit": COMMITS[product], "error": "",
            "views": [
                {"title": title, "file": file, "path": path,
                 "revision": "1.0.0", "status": "Владелец DigitalHouses · только просмотр",}
                for file, title, path in views]}


class FakeCatalog:
    def __init__(self, entries):
        self.entries = entries
        self.calls = 0

    def inspect(self, claims):
        self.calls += 1
        return self.entries


class LocalAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root/"dashboards/dh/views"
        self.folder.mkdir(parents=True)
        (self.root/"dashboards/dh/ui.yaml").write_text(
            "title: DigitalHouses\nviews: !include_dir_list views/\n")
        (self.root/".storage").mkdir()
        self.pve1 = yaml_view(PVE, "Proxmox", "dh_pve_agent")
        self.pve2 = yaml_view(PVE, "Электропитание", "dh_pve_agent_ups")
        self.plex = yaml_view(PLEX, "Plex", "dh-plex-agent")
        self.contents = {
            PVE+"/dashboards/ru/10_pve_proxmox.yaml": self.pve1,
            PVE+"/dashboards/ru/11_pve_ups.yaml": self.pve2,
            PLEX+"/dashboards/ru/10_plex.yaml": self.plex,
        }
        self.catalog = FakeCatalog([
            entry(PVE, [("10_pve_proxmox.yaml", "Proxmox", "dh_pve_agent"),
                        ("11_pve_ups.yaml", "Электропитание", "dh_pve_agent_ups")]),
            entry(PLEX, [("10_plex.yaml", "Plex", "dh-plex-agent")]),
        ])
        self.fetches = []

    def audit(self):
        def source(repo, path, sha):
            self.fetches.append((repo, path, sha))
            return self.contents[path]
        return LocalAuditor(self.root, catalog=self.catalog, fetcher=source,
                            require_readonly=False).inspect({})

    def test_two_pve_views_exact_and_missing_plex(self):
        (self.folder/"10_pve_proxmox.yaml").write_bytes(self.pve1)
        (self.folder/"11_pve_ups.yaml").write_bytes(self.pve2)
        report = self.audit()
        self.assertTrue(report["ready"])
        self.assertFalse(report["write_enabled"])
        self.assertEqual([v["kind"] for p in report["products"] for v in p["views"]],
                         ["identical", "identical", "missing"])
        self.assertEqual(len(self.fetches), 3)
        self.assertEqual({sha for _,_,sha in self.fetches}, set(COMMITS.values()))
        self.assertTrue(all(repo == REPO for repo, _, _ in self.fetches))

    def test_owned_dedicated_repo_root_directory(self):
        self.catalog.entries = [{
            "product": PLEX, "repository": "https://github.com/DigitalHouses/recorder",
            "product_path": ".", "version": "0.1.28", "commit": "c"*40,
            "error": "", "views": [{
                "title": "Recorder", "file": "10_recorder.yaml", "path": "recorder",
                "revision": "—", "status": "Владелец DigitalHouses · только просмотр",,
            }],
        }]
        source = (b"type: sections\ntitle: Recorder\npath: recorder\nsections: []\n")
        source_path = "dashboards/ru/10_recorder.yaml"
        captured = []
        def reader(repo, path, sha):
            captured.append((repo,path,sha))
            return source
        report = LocalAuditor(self.root, catalog=self.catalog, fetcher=reader,
                              require_readonly=False).inspect({})
        self.assertTrue(report["ready"])
        self.assertEqual(report["products"][0]["views"][0]["kind"], "missing")
        self.assertEqual(captured, [(
            "https://github.com/DigitalHouses/recorder", source_path, "c"*40,
        )])

    def test_semantically_equal_but_comments_changed(self):
        (self.folder/"10_pve_proxmox.yaml").write_bytes(
            self.pve1.replace(b"# DH-View-Version: 1.0.0\n", b"# Local note: old header\n"))
        report = self.audit()
        v = report["products"][0]["views"][0]
        self.assertEqual(v["kind"], "equivalent")
        self.assertNotEqual(v["local_sha256"], v["source_sha256"])
        self.assertGreater(v["diff"]["added"] + v["diff"]["removed"], 0)

    def test_modified_view_reports_bounded_diff_without_writing(self):
        changed = self.pve1.replace(b"title: Proxmox", b"title: My CORE Proxmox")
        target = self.folder/"10_pve_proxmox.yaml"
        target.write_bytes(changed)
        before = target.read_bytes()
        report = self.audit()
        row = report["products"][0]["views"][0]
        self.assertEqual(row["kind"], "different")
        self.assertIn("My CORE Proxmox", row["diff"]["preview"])
        self.assertLess(len(row["diff"]["preview"]), 5000)
        self.assertEqual(target.read_bytes(), before)

    def test_path_found_under_different_local_filename(self):
        (self.folder/"97_custom.yaml").write_bytes(self.pve1)
        row = self.audit()["products"][0]["views"][0]
        self.assertEqual(row["kind"], "identical")
        self.assertEqual(row["local_file"], "97_custom.yaml")

    def test_occupied_filename_is_conflict(self):
        (self.folder/"10_pve_proxmox.yaml").write_bytes(
            yaml_view(PVE, "User", "user-dashboard"))
        row = self.audit()["products"][0]["views"][0]
        self.assertEqual(row["kind"], "collision")

    def test_duplicate_local_view_paths_are_reported(self):
        (self.folder/"10_pve_proxmox.yaml").write_bytes(self.pve1)
        (self.folder/"99_dup.yaml").write_bytes(self.pve1)
        report = self.audit()
        self.assertTrue(any("Duplicate" in issue for issue in report["issues"]))
        self.assertEqual(report["products"][0]["views"][0]["kind"], "collision")

    def test_storage_mode_plex_path_prevents_false_missing(self):
        storage = {
            "version": 1, "key": "lovelace.plex", "private_token": "PRIVATE_SHOULD_NOT_LEAK",
            "data": {"config": {"views": [{"path": "dh-plex-agent", "title": "Plex"}]}}
        }
        (self.root/".storage/lovelace.plex").write_text(json.dumps(storage))
        report = self.audit()
        self.assertEqual(report["products"][1]["views"][0]["kind"], "storage")
        self.assertEqual(report["storage_files_examined"], 1)
        self.assertNotIn("PRIVATE_SHOULD_NOT_LEAK", json.dumps(report))
        self.assertNotIn("lovelace.plex", json.dumps(report))

    def test_broken_storage_blocks_audit_without_leaking_file(self):
        (self.root/".storage/lovelace.plex").write_text("not private-safe JSON")
        report = self.audit()
        self.assertFalse(report["ready"])
        self.assertFalse(report["products"])
        self.assertNotIn("private-safe", json.dumps(report))

    def test_symlink_source_path_rejected(self):
        real = self.root/"secret-simulated.yaml"
        real.write_bytes(self.pve1)
        (self.folder/"10_pve_proxmox.yaml").symlink_to(real)
        report = self.audit()
        self.assertFalse(report["ready"])
        self.assertTrue(report["issues"])

    def test_writable_config_mount_blocks_before_reading_any_files(self):
        with patch("local_audit.os.statvfs", return_value=SimpleNamespace(f_flag=0)):
            result = LocalAuditor(self.root, catalog=self.catalog,
                                  require_readonly=True).inspect({})
        self.assertFalse(result["ready"])
        self.assertTrue(any("not read-only" in issue for issue in result["issues"]))
        self.assertEqual(self.catalog.calls, 0)
        self.assertEqual(result["products"], [])

    def test_unavailable_config_fails_closed_without_github_requests(self):
        self.folder.rename(self.root/"saved_views")
        missing = self.root/"not-a-real-home-mount"
        r = LocalAuditor(missing, catalog=self.catalog, fetcher=lambda *args:
                         (_ for _ in ()).throw(AssertionError("unexpected fetch")),
                         require_readonly=True).inspect({})
        self.assertFalse(r["ready"])
        self.assertEqual(self.catalog.calls, 0)

    def test_local_diff_requires_opt_in_get_http_post_stays_405(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            products=ProductSources(root/"sources.json")
            inventory=Inventory(root/"inventory.json")
            calls=[]
            def audit(records):
                calls.append(1)
                return {"ready":True, "issues":[], "readonly":True,
                        "write_enabled":False, "storage_files_examined":0,
                        "products":[{"product":PLEX,"version":"0.8.18",
                                     "commit":COMMITS[PLEX],"source_error":"",
                                     "views":[{"title":"Plex","source_file":"10_plex.yaml",
                                               "view_path":"dh-plex-agent",
                                               "source_status":"owner-only",
                                               "local_file":"", "kind":"missing",
                                               "status":"Локальный YAML отсутствует",
                                               "source_sha256":"a"*64,
                                               "local_sha256":"","diff":None}]}]}
            server=make_server(products,inventory,version="0.2.0",port=0,
                               audit=audit)
            server.timeout=2
            worker=threading.Thread(
                target=lambda:[server.handle_request() for _ in range(3)],daemon=True)
            try:
                worker.start()
                self.assertEqual(fetch(server)[0],200)
                self.assertEqual(len(calls),0)
                status,body=fetch(server,path="/?local=1")
                self.assertEqual(status,200)
                self.assertEqual(len(calls),1)
                self.assertIn("Локальный YAML отсутствует",body)
                self.assertEqual(fetch(server,method="POST")[0],405)
            finally:
                server.server_close()
                worker.join(timeout=4)


if __name__ == "__main__":
    unittest.main()
