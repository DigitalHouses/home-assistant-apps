"""GitHub panel YAML -> HA Storage dashboards via official WebSocket."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from dashboard_runtime import DashboardPublisher, DashboardError
from panel_config import parse_panel, PanelError


def panel(slug="dh-system", refs=None, *, admin=True, title="DH System"):
    refs = refs if refs is not None else [{"product": "pve", "path": "proxmox"}]
    return {"slug": slug, "title": title, "icon": "mdi:server",
            "show_in_sidebar": True, "require_admin": admin, "views": refs}


def source(product="pve", path="proxmox", title="Proxmox"):
    return {(product, path): {"bytes": (
        f"title: {title}\npath: {path}\ntype: sections\nsections: []\n"
    ).encode()}}


class FakeWS:
    def __init__(self):
        self.entries = []
        self.configs = {}
        self.calls = []
        self.fail_save = False

    def session(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def request(self, kind, **kwargs):
        self.calls.append((kind, kwargs))
        if kind == "lovelace/dashboards/list":
            return json.loads(json.dumps(self.entries))
        if kind == "lovelace/dashboards/create":
            entry = {"id": len(self.entries) + 1, "mode": "storage", **kwargs}
            self.entries.append(entry)
            return {"id": entry["id"]}
        if kind == "lovelace/dashboards/update":
            entry = next(e for e in self.entries if e.get("id") == kwargs["dashboard_id"])
            entry.update({k: v for k, v in kwargs.items() if k != "dashboard_id"})
            return {}
        if kind == "lovelace/config":
            slug = kwargs["url_path"]
            if slug not in self.configs:
                raise DashboardError("lovelace/config: config_not_found")
            return json.loads(json.dumps(self.configs[slug]))
        if kind == "lovelace/config/save":
            if self.fail_save:
                raise DashboardError("save failed")
            self.configs[kwargs["url_path"]] = json.loads(json.dumps(kwargs["config"]))
            return None
        raise AssertionError(kind)


class DeclarativeDashboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path = Path(self.tmp.name)
        self.ws = FakeWS()
        self.publisher = DashboardPublisher(path, path / "data", transport=self.ws)

    def test_panel_parser_preserves_list_order(self):
        raw = (b"title: DH System\nrequire_admin: true\nviews:\n"
               b"  - product: plex\n    path: plex\n"
               b"  - product: pve\n    path: proxmox\n")
        parsed = parse_panel("dh-system.yaml", raw)
        self.assertEqual([r["path"] for r in parsed["views"]], ["plex", "proxmox"])

    def test_native_panel_metadata_and_view_order(self):
        p = panel(refs=[
            {"product": "internet", "path": "internet", "overrides": {"title": "Internet"}},
            {"product": "pve", "path": "proxmox", "overrides": {"icon": None}},
        ])
        sources = {**source("pve", "proxmox"), **source("internet", "internet")}
        result = self.publisher.sync([p], sources)
        self.assertEqual(result["state"], "Updated")
        self.assertEqual([x["path"] for x in self.ws.configs["dh-system"]["views"]],
                         ["internet", "proxmox"])
        self.assertEqual(self.ws.configs["dh-system"]["views"][0]["title"], "Internet")
        self.assertTrue(self.ws.entries[0]["require_admin"])
        self.assertEqual(self.publisher.sync([p], sources)["state"], "Current")

    def test_same_view_can_be_reused_in_two_panels(self):
        src = source("internet", "internet")
        refs = [{"product": "internet", "path": "internet",
                 "overrides": {"show_icon_and_title": True}}]
        public = panel("dh-home", refs, admin=False, title="DH Home")
        admin = panel("dh-system", refs, admin=True)
        self.assertEqual(self.publisher.sync([admin, public], src)["state"], "Updated")
        self.assertEqual([x["path"] for x in self.ws.configs["dh-system"]["views"]], ["internet"])
        self.assertEqual([x["path"] for x in self.ws.configs["dh-home"]["views"]], ["internet"])
        self.assertTrue(next(e for e in self.ws.entries if e["url_path"] == "dh-system")["require_admin"])
        self.assertFalse(next(e for e in self.ws.entries if e["url_path"] == "dh-home")["require_admin"])

    def test_panel_metadata_updates_without_recreating(self):
        src = source()
        self.publisher.sync([panel()], src)
        changed = panel(title="Core Servers", admin=False)
        changed["icon"] = "mdi:lan"
        result = self.publisher.sync([changed], src)
        self.assertEqual(result["state"], "Updated")  # Dashboard metadata changed.
        entry = self.ws.entries[0]
        self.assertEqual(entry["title"], "Core Servers")
        self.assertEqual(entry["icon"], "mdi:lan")
        self.assertFalse(entry["require_admin"])
        self.assertEqual(sum(k == "lovelace/dashboards/create" for k, _ in self.ws.calls), 1)

    def test_removed_reference_removes_previous_view_only_in_that_panel(self):
        src = source()
        self.publisher.sync([panel()], src)
        self.publisher.sync([panel(refs=[])], src)
        self.assertEqual(self.ws.configs["dh-system"]["views"], [])

    def test_no_mqtt_product_means_no_view_and_no_new_panel(self):
        report = self.publisher.sync([panel()], {})
        self.assertEqual(report["dashboards"][0]["state"], "No active views")
        self.assertEqual(self.ws.entries, [])

    def test_duplicate_path_in_same_panel_is_error(self):
        refs = [{"product": "pve", "path": "same", "overrides": {}},
                {"product": "plex", "path": "same", "overrides": {}}]
        src = {**source("pve", "same"), **source("plex", "same")}
        report = self.publisher.sync([panel(refs=refs)], src)
        self.assertEqual(report["state"], "Partial")
        self.assertIn("Duplicate view path", report["issues"][0])

    def test_one_broken_panel_does_not_block_others(self):
        bad = panel("dh-bad", [{"product": "pve", "path": "nope", "overrides": {}},
                               {"product": "plex", "path": "nope", "overrides": {}}])
        good = panel("dh-good", [{"product": "pve", "path": "proxmox", "overrides": {}}])
        src = {**source("pve", "nope"), **source("plex", "nope"), **source()}
        report = self.publisher.sync([bad, good], src)
        self.assertEqual(report["state"], "Partial")
        self.assertEqual(self.ws.configs["dh-good"]["views"][0]["path"], "proxmox")

    def test_yaml_managed_panel_is_not_overwritten(self):
        self.ws.entries.append({"id": 8, "url_path": "dh-system", "mode": "yaml"})
        result = self.publisher.sync([panel()], source())
        self.assertEqual(result["state"], "Partial")
        self.assertEqual(self.ws.configs, {})

    def test_save_failure_is_reported_without_removing_existing_config(self):
        self.publisher.sync([panel()], source())
        existing = self.ws.configs["dh-system"]
        self.ws.fail_save = True
        report = self.publisher.sync([panel(refs=[])], source())
        self.assertEqual(report["state"], "Partial")
        self.assertEqual(self.ws.configs["dh-system"], existing)

    def test_no_panel_files_does_not_touch_unrelated_panels(self):
        self.ws.entries.append({"id": 3, "url_path": "user-dashboard", "mode": "storage"})
        self.assertEqual(self.publisher.sync([], source())["state"], "No panel YAML")
        self.assertEqual(len(self.ws.calls), 0)

    def test_parser_rejects_bad_access_and_duplicate_references(self):
        for raw in (b"title: X\nviews: []\n",
                    b'title: X\nrequire_admin: "yes"\nviews: []\n',
                    b"title: X\nrequire_admin: true\nviews:\n"
                    b"  - product: pve\n    path: x\n"
                    b"  - product: pve\n    path: x\n"):
            with self.subTest(raw=raw):
                with self.assertRaises(PanelError):
                    parse_panel("dh-system.yaml", raw)


if __name__ == "__main__":
    unittest.main()
