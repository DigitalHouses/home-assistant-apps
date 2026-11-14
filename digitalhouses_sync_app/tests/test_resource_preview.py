"""Resource discovery uses pinned commits and requires an explicit read-only GET."""
from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path

from catalog_web import make_server
from discovery_contract import ProductSources
from inventory import Inventory
from resource_preview import PINS, PreviewCatalog, compatible
from test_catalog_web import fetch

REPO = "https://github.com/DigitalHouses/home-assistant-apps"


def claim(product, version, repo=REPO):
    return {"product_id": product, "version": version,
            "repository": repo, "product_path": product, "schema": 1, "type": "agent"}


def raw_view(name, path, constraint, view_id="dh_pve_agent"):
    return (f"# DH-View: {view_id}\n"
            f"# DH-View-Version: 1.0.0\n"
            f"# DH-Compatible-Agent: {constraint}\n\n"
            f"type: sections\ntitle: {name}\npath: {path}\nsections: []\n").encode()


class PinnedDiscoveryTests(unittest.TestCase):
    def test_pve_discovers_both_views_from_directory(self):
        product = "digitalhouses_pve_agent"
        seen = []
        def listing(pid, sha):
            self.assertEqual((pid, sha), (product, PINS[product].commit))
            return [{"type":"file","name":n,"path":product+"/dashboards/ru/"+n}
                    for n in ("11_pve_ups.yaml","10_pve_proxmox.yaml")]
        def reader(path, sha):
            seen.append(path)
            return raw_view(path.split("/")[-1], "dh_pve_ups" if "ups" in path else "dh_pve",
                            ">=0.5.88,<0.5.89")
        found = PreviewCatalog(listing=listing, reader=reader).inspect({
            product+"/synthetic": claim(product, "0.5.89")
        })[0]
        self.assertEqual([v["file"] for v in found["views"]],
                         ["10_pve_proxmox.yaml", "11_pve_ups.yaml"])
        self.assertEqual(len(seen), 2)
        self.assertTrue(all(v["blocked"] for v in found["views"]))
        self.assertTrue(all("Источник не утверждён" in v["status"] for v in found["views"]))
        self.assertTrue(all("Нет подтверждения совместимости" in v["status"]
                            for v in found["views"]))

    def test_plex_view_found_but_0818_outside_compatibility(self):
        product = "digitalhouses_plex_agent"
        viewpath = product + "/dashboards/ru/10_plex.yaml"
        catalog = PreviewCatalog(
            listing=lambda pid,sha:[{"type":"file","name":"10_plex.yaml","path":viewpath}],
            reader=lambda p,sha:raw_view("Plex","dh-plex-agent",">=0.8.17,<0.8.18","dh_plex_agent")
        )
        row = catalog.inspect({product+"/default":claim(product,"0.8.18")})[0]
        self.assertEqual([v["file"] for v in row["views"]],["10_plex.yaml"])
        self.assertTrue(row["views"][0]["blocked"])
        self.assertTrue(compatible("0.8.17",">=0.8.17,<0.8.18"))
        self.assertFalse(compatible("0.8.18",">=0.8.17,<0.8.18"))
        self.assertFalse(compatible("unknown",">=0.8.17,<0.8.18"))

    def test_mqtt_unknown_repo_or_product_never_triggers_download(self):
        def forbidden(*args):
            raise AssertionError("Unsafe MQTT input reached a GitHub fetch")
        inspector=PreviewCatalog(listing=forbidden,reader=forbidden)
        rows=inspector.inspect({
            "digitalhouses_plex_agent/default":claim(
                "digitalhouses_plex_agent","0.8.18",
                "https://github.com/DigitalHouses/other"),
            "digitalhouses_unknown_agent/default":claim(
                "digitalhouses_unknown_agent","1.0.0")
        })
        self.assertEqual(len(rows),2)
        self.assertTrue(all(row["error"] for row in rows))
        self.assertTrue(all(not row["views"] for row in rows))

    def test_duplicate_view_path_rejected_as_whole_group(self):
        product="digitalhouses_pve_agent"
        inspector=PreviewCatalog(
            listing=lambda pid,sha:[{"type":"file","name":n,
                "path":product+"/dashboards/ru/"+n} for n in ("10_a.yaml","11_b.yaml")],
            reader=lambda p,sha:raw_view("duplicate","same",">=0.5.88,<0.5.89")
        )
        row=inspector.inspect({product+"/default":claim(product,"0.5.88")})[0]
        self.assertIn("Duplicate Lovelace",row["error"])
        self.assertEqual(row["views"],[])

    def test_unsafe_listing_cannot_be_used_as_download_url(self):
        product="digitalhouses_pve_agent"
        inspector=PreviewCatalog(
            listing=lambda p,sha:[{"type":"file","name":"../evil.yaml",
                "path":product+"/dashboards/ru/../evil.yaml"}],
            reader=lambda *args: (_ for _ in ()).throw(AssertionError("Unsafe fetch"))
        )
        row=inspector.inspect({product+"/default":claim(product,"0.5.88")})[0]
        self.assertIn("Unsafe YAML",row["error"])

    def test_mismatched_view_identity_fails_closed(self):
        product="digitalhouses_plex_agent"
        inspector=PreviewCatalog(
            listing=lambda p,sha:[{"type":"file","name":"10_plex.yaml",
                "path":product+"/dashboards/ru/10_plex.yaml"}],
            reader=lambda p,sha:raw_view("Plex","dh-plex-agent",
                ">=0.8.17,<0.8.18","dh_pve_agent"),
        )
        row=inspector.inspect({product+"/default":claim(product,"0.8.18")})[0]
        self.assertIn("mismatched canonical view",row["error"])
        self.assertEqual(row["views"],[])

    def test_get_preview_not_automatic_and_post_still_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            sources=ProductSources(root/"sources.json")
            inventory=Inventory(root/"inventory.json")
            product="digitalhouses_plex_agent"
            sources.apply("DigitalHouses/Global/"+product+"/sync",
                json.dumps(claim(product,"0.8.18")))
            called=[]
            def inspect(records):
                called.append(1)
                return PreviewCatalog(
                    listing=lambda p,sha:[{"type":"file","name":"10_plex.yaml",
                         "path":product+"/dashboards/ru/10_plex.yaml"}],
                    reader=lambda p,sha:raw_view("Plex","dh-plex-agent",">=0.8.17,<0.8.18")
                ).inspect(records)
            server=make_server(sources,inventory,version="0.1.3",port=0,inspect=inspect)
            server.timeout=2
            thread=threading.Thread(target=lambda:[server.handle_request() for _ in range(3)],
                                     daemon=True)
            try:
                thread.start()
                status,body=fetch(server)
                self.assertEqual(status,200)
                self.assertEqual(called,[])
                self.assertIn("Проверить GitHub-ресурсы",body)
                status,body=fetch(server,path="/?resources=1")
                self.assertEqual(status,200)
                self.assertEqual(len(called),1)
                self.assertIn("10_plex.yaml",body)
                self.assertIn("Нет подтверждения совместимости",body)
                self.assertEqual(fetch(server,method="POST")[0],405)
            finally:
                server.server_close()
                thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
