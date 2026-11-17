"""Live Dashboard registration: YAML files -> HA official WebSocket API."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from dashboard_runtime import DashboardPublisher, DashboardError, URL_PATH
from auto_sync import AutoSync
from test_auto_sync import FakeBackend, CLAIMS


class FakeSession:
    def __init__(self, backend):
        self.backend = backend

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def request(self, kind, **kwargs):
        self.backend.calls.append((kind, kwargs))
        if kind == "lovelace/dashboards/list":
            return list(self.backend.dashboards)
        if kind == "lovelace/dashboards/create":
            if self.backend.create_fail:
                raise DashboardError("creation failed")
            self.backend.dashboards.append(
                {"url_path": kwargs["url_path"], "mode": "storage",
                 "title": kwargs["title"], "show_in_sidebar": kwargs["show_in_sidebar"]})
            return {"id": "digital-houses"}
        if kind == "lovelace/config":
            if self.backend.config is None:
                raise DashboardError("lovelace/config: config_not_found")
            return json.loads(json.dumps(self.backend.config))
        if kind == "lovelace/config/save":
            if self.backend.save_fail:
                raise DashboardError("save failed")
            self.backend.config = json.loads(json.dumps(kwargs["config"]))
            return None
        raise AssertionError(kind)


class FakeTransport:
    def __init__(self):
        self.dashboards = [{"url_path": "lovelace", "mode": "storage", "title": "Overview"}]
        self.config = None
        self.calls = []
        self.create_fail = False
        self.save_fail = False

    def session(self):
        return FakeSession(self)


class DashboardRuntimeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name)
        self.root = base / "homeassistant"
        self.views = self.root / "dashboards/dh/views"
        self.views.mkdir(parents=True)
        self.data = base / "data"
        self.transport = FakeTransport()
        self.publisher = DashboardPublisher(self.root, self.data, transport=self.transport)

    def view(self, name, path, *, extra=""):
        (self.views / name).write_text(
            f"title: {path}\npath: {path}\ntype: sections\nsections: []\n" + extra
        )

    def test_registers_dashboard_and_publishes_two_views(self):
        self.view("10_pve_proxmox.yaml", "dh_pve_agent")
        self.view("11_pve_ups.yaml", "dh_pve_agent_ups")
        first = self.publisher.sync()
        self.assertEqual(first, {"state": "Updated", "url": "/digital-houses/"})
        self.assertEqual(len(self.transport.config["views"]), 2)
        self.assertEqual([x["path"] for x in self.transport.config["views"]],
                         ["dh_pve_agent", "dh_pve_agent_ups"])
        self.assertEqual(self.transport.dashboards[-1]["title"], "DigitalHouses")
        self.assertTrue(self.transport.dashboards[-1]["show_in_sidebar"])
        second = self.publisher.sync()
        self.assertEqual(second["state"], "Current")
        self.assertEqual([x[0] for x in self.transport.calls].count(
            "lovelace/dashboards/create"), 1)
        self.assertEqual([x[0] for x in self.transport.calls].count(
            "lovelace/config/save"), 1)

    def test_same_view_path_in_another_dashboard_does_not_block(self):
        self.transport.dashboards.append(
            {"url_path": "user-dashboard", "mode": "storage", "title": "User"})
        self.view("10_pve_proxmox.yaml", "dh_pve_agent")
        self.assertEqual(self.publisher.sync()["state"], "Updated")
        self.assertEqual(len(self.transport.dashboards), 3)

    def test_update_preserves_unmanaged_storage_view_and_backs_up(self):
        self.view("10_pve_proxmox.yaml", "dh_pve_agent")
        self.publisher.sync()
        self.transport.config["views"].append({"title": "Local", "path": "local"})
        self.view("10_pve_proxmox.yaml", "dh_pve_agent", extra="icon: mdi:server\n")
        self.publisher.sync()
        self.assertEqual(self.transport.config["views"][0]["icon"], "mdi:server")
        self.assertEqual(self.transport.config["views"][1]["path"], "local")
        self.assertGreaterEqual(len(list(self.data.glob("dashboard-backup-*.json"))), 2)

    def test_occupied_unmanaged_panel_is_not_overwritten(self):
        self.view("10_pve_proxmox.yaml", "dh_pve_agent")
        self.transport.dashboards.append(
            {"url_path": URL_PATH, "mode": "storage", "title": "User"})
        with self.assertRaisesRegex(DashboardError, "not owned"):
            self.publisher.sync()
        self.assertIsNone(self.transport.config)
        self.assertFalse((self.data / "dashboard-managed.json").exists())

    def test_occupied_unmanaged_view_is_not_overwritten(self):
        self.view("10_pve_proxmox.yaml", "dh_pve_agent")
        self.publisher.sync()
        self.transport.config["views"].append({"path": "manual", "title": "Local"})
        self.view("12_manual.yaml", "manual")
        with self.assertRaisesRegex(DashboardError, "Unmanaged view"):
            self.publisher.sync()
        self.assertEqual(self.transport.config["views"][-1]["title"], "Local")

    def test_existing_yaml_dashboard_is_preserved(self):
        self.view("10_pve_proxmox.yaml", "dh_pve_agent")
        self.transport.dashboards.append(
            {"url_path": "digital-houses", "mode": "yaml", "title": "DigitalHouses"})
        self.transport.config = {"views": [{"path": "dh_pve_agent", "title": "Existing"}]}
        self.assertEqual(self.publisher.sync()["state"], "YAML registered")
        self.assertFalse(any(c[0] == "lovelace/config/save" for c in self.transport.calls))

    def test_yaml_dashboard_must_really_contain_the_views(self):
        self.view("10_pve_proxmox.yaml", "dh_pve_agent")
        self.transport.dashboards.append(
            {"url_path": "digital-houses", "mode": "yaml", "title": "DigitalHouses"})
        self.transport.config = {"views": [{"path": "other", "title": "Other"}]}
        with self.assertRaisesRegex(DashboardError, "does not include"):
            self.publisher.sync()

    def test_no_published_views_does_not_create_empty_panel(self):
        self.assertEqual(self.publisher.sync()["state"], "No published views")
        self.assertFalse(self.transport.calls)

    def test_dashboard_error_propagates_into_sync_status(self):
        self.transport.create_fail = True
        app = AutoSync(self.root, self.data, backend=FakeBackend(), publisher=self.publisher)
        (self.root / "configuration.yaml").write_text(
            "homeassistant:\n  packages: !include_dir_merge_named packages/\n")
        result = app.sync(CLAIMS)
        self.assertEqual(result["state"], "Partial")
        self.assertEqual(result["updated"], 2)
        self.assertIn("creation failed", result["issues"][0])

    def test_dashboard_status_is_visible_after_success(self):
        app = AutoSync(self.root, self.data, backend=FakeBackend(), publisher=self.publisher)
        (self.root / "configuration.yaml").write_text(
            "homeassistant:\n  packages: !include_dir_merge_named packages/\n")
        result = app.sync(CLAIMS)
        self.assertEqual(result["state"], "OK", result["issues"])
        self.assertEqual(result["dashboard"]["url"], "/digital-houses/")
        again = app.sync(CLAIMS)
        self.assertEqual(again["dashboard"]["state"], "Current")


if __name__ == "__main__":
    unittest.main()
