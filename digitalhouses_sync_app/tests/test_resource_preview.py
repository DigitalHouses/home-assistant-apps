"""Dynamic, read-only GitHub discovery: owner-only product admission."""
from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path

from catalog_web import make_server
from discovery_contract import ProductSources
from inventory import Inventory
from resource_preview import PreviewCatalog, PreviewError, parse_view
from test_catalog_web import fetch

REPO = "https://github.com/DigitalHouses/home-assistant-apps"
OTHER = "https://github.com/DigitalHouses/recorder"
SHA = "a" * 40


def claim(product, version, repo=REPO, path=None):
    return {"product_id": product, "version": version, "repository": repo,
            "product_path": path if path is not None else product}


def raw_view(title, view_path, header=True):
    top = (
        "# DH-View: any_name\n# DH-View-Version: 1.0.0\n"
        "# DH-Compatible-App: >=0.1.28,<0.1.29\n" if header else ""
    )
    return (top + f"type: sections\ntitle: {title}\npath: {view_path}\nsections: []\n").encode()


class OwnerOnlyDiscoveryTests(unittest.TestCase):
    def test_two_pve_views_are_enumerated_without_product_pins(self):
        product = "digitalhouses_pve_agent"
        received = []
        def listing(repo, folder, sha):
            received.append((repo, folder, sha))
            return [{"name": name, "path": product+"/dashboards/ru/"+name, "type": "file"}
                    for name in ("11_pve_ups.yaml", "10_pve_proxmox.yaml")]
        inspector = PreviewCatalog(
            resolver=lambda repo: (SHA, "main"),
            listing=listing,
            reader=lambda repo,path,sha: raw_view(path.split("/")[-1], path),
        )
        row = inspector.inspect({product+"/a": claim(product, "9999.0")})[0]
        self.assertEqual([v["file"] for v in row["views"]],
                         ["10_pve_proxmox.yaml", "11_pve_ups.yaml"])
        self.assertEqual(received, [(REPO, product, SHA)])
        self.assertTrue(all(v["blocked"] is False for v in row["views"]))
        self.assertEqual(row["commit"], SHA)

    def test_unlisted_recorder_works_without_compatible_header(self):
        product = "digitalhouses_recorder_app"
        inspector = PreviewCatalog(
            resolver=lambda repo: (SHA, "main"),
            listing=lambda repo,folder,sha: [{
                "name":"10_recorder.yaml", "type":"file",
                "path": product+"/dashboards/ru/10_recorder.yaml",
            }],
            reader=lambda repo,path,sha: raw_view("DH Recorder", "recorder", header=False),
        )
        result = inspector.inspect({product+"/default":claim(product, "0.1.28")})[0]
        self.assertEqual(result["error"], "")
        self.assertEqual(result["views"][0]["path"], "recorder")
        self.assertEqual(result["views"][0]["constraint"], "—")
        self.assertFalse(result["views"][0]["blocked"])

    def test_other_org_owned_repo_and_root_folder(self):
        product = "custom_tool"
        seen = []
        inspector = PreviewCatalog(
            resolver=lambda repo: (SHA, "development"),
            listing=lambda repo,folder,sha: (
                seen.append((repo,folder,sha)) or [
                    {"name":"dashboard.yaml","type":"file","path":"dashboards/ru/dashboard.yaml"}
                ]),
            reader=lambda repo,path,sha: raw_view("Custom","custom"),
        )
        row=inspector.inspect({product+"/default":claim(product,"unknown",OTHER,".")})[0]
        self.assertEqual(seen, [(OTHER, ".", SHA)])
        self.assertEqual(row["views"][0]["path"],"custom")

    def test_invalid_owner_has_no_network_calls(self):
        inspector=PreviewCatalog(
            resolver=lambda *args: (_ for _ in ()).throw(AssertionError("owner bypass")),
            listing=lambda *args: (_ for _ in ()).throw(AssertionError("listing bypass")),
        )
        result=inspector.inspect({"bad/default":claim(
            "bad", "1.0.0", "https://github.com/SomebodyElse/app")})[0]
        self.assertIn("DigitalHouses", result["error"])

    def test_bogus_git_listing_paths_do_not_become_downloads(self):
        product="digitalhouses_pve_agent"
        inspector=PreviewCatalog(
            resolver=lambda repo: (SHA,"main"),
            listing=lambda repo,folder,sha: [{
                "name":"../private.yaml","type":"file",
                "path":product+"/dashboards/ru/../private.yaml",
            }],
            reader=lambda *args: (_ for _ in ()).throw(AssertionError("unsafe fetch")),
        )
        row=inspector.inspect({product+"/default":claim(product, "0.5.89")})[0]
        self.assertIn("Unsafe GitHub", row["error"])

    def test_duplicate_lovelace_paths_are_reported(self):
        product="digitalhouses_pve_agent"
        inspector=PreviewCatalog(
            resolver=lambda repo: (SHA,"main"),
            listing=lambda repo,folder,sha:[
                {"name":name,"type":"file","path":product+"/dashboards/ru/"+name}
                for name in ("10_a.yaml","11_b.yaml")],
            reader=lambda repo,path,sha: raw_view("Title","same"),
        )
        row=inspector.inspect({product+"/default":claim(product,"0.5.89")})[0]
        self.assertIn("Duplicate Lovelace",row["error"])
        self.assertEqual(row["views"],[])

    def test_view_headers_are_optional_information_only(self):
        output=parse_view(raw_view("Recorder","recorder",header=False),
                          "dashboards/ru/10_recorder.yaml","digitalhouses_recorder_app")
        self.assertEqual(output["revision"],"—")
        self.assertEqual(output["constraint"],"—")

    def test_preview_requires_explicit_get_and_post_stays_disabled(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            sources=ProductSources(root/"sources.json")
            inventory=Inventory(root/"inventory.json")
            product="digitalhouses_recorder_app"
            sources.apply("DigitalHouses/Global/"+product+"/sync",
                          json.dumps(claim(product,"0.1.28")))
            calls=[]
            def inspect(records):
                calls.append(1)
                return PreviewCatalog(
                    resolver=lambda repo:(SHA,"main"),
                    listing=lambda repo,folder,sha:[{
                        "name":"10_recorder.yaml","type":"file",
                        "path":product+"/dashboards/ru/10_recorder.yaml"}],
                    reader=lambda repo,path,sha:raw_view("Recorder","recorder",header=False),
                ).inspect(records)
            server=make_server(sources,inventory,version="0.2.1",port=0,inspect=inspect)
            server.timeout=2
            worker=threading.Thread(target=lambda:[
                server.handle_request() for _ in range(3)],daemon=True)
            try:
                worker.start()
                self.assertEqual(fetch(server)[0],200)
                self.assertEqual(calls,[])
                status,body=fetch(server,path="/?resources=1")
                self.assertEqual(status,200)
                self.assertEqual(len(calls),1)
                self.assertIn("10_recorder.yaml",body)
                self.assertIn("Владелец DigitalHouses",body)
                self.assertEqual(fetch(server,method="POST")[0],405)
            finally:
                server.server_close()
                worker.join(timeout=4)


if __name__ == "__main__":
    unittest.main()
