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
            config = self.backend.configs.get(kwargs.get("url_path", URL_PATH))
            if config is None:
                raise DashboardError("lovelace/config: config_not_found")
            return json.loads(json.dumps(config))
        if kind == "lovelace/config/save":
            if self.backend.save_fail:
                raise DashboardError("save failed")
            self.backend.configs[kwargs["url_path"]] = json.loads(
                json.dumps(kwargs["config"]))
            return None
        raise AssertionError(kind)


class FakeTransport:
    def __init__(self):
        self.dashboards = [{"url_path": "lovelace", "mode": "storage", "title": "Overview"}]
        self.configs = {}
        self.calls = []
        self.create_fail = False
        self.save_fail = False

    @property
    def config(self):
        return self.configs.get(URL_PATH)

    @config.setter
    def config(self, value):
        self.configs[URL_PATH] = value

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
        self.assertEqual(first["state"], "Updated")
        self.assertEqual(first["url"], "/digital-houses/")
        self.assertEqual(first["dashboards"][0]["views"], 2)
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
        result = self.publisher.sync()
        self.assertEqual(result["state"], "Partial")
        self.assertIn("not owned", result["issues"][0])
        self.assertIsNone(self.transport.config)
        self.assertFalse((self.data / "dashboard-managed.json").exists())

    def test_occupied_unmanaged_view_is_not_overwritten(self):
        self.view("10_pve_proxmox.yaml", "dh_pve_agent")
        self.publisher.sync()
        self.transport.config["views"].append({"path": "manual", "title": "Local"})
        self.view("12_manual.yaml", "manual")
        result = self.publisher.sync()
        self.assertEqual(result["state"], "Partial")
        self.assertIn("Unmanaged view", result["issues"][0])
        self.assertEqual(self.transport.config["views"][-1]["title"], "Local")

    def test_existing_yaml_dashboard_is_preserved(self):
        self.view("10_pve_proxmox.yaml", "dh_pve_agent")
        self.transport.dashboards.append(
            {"url_path": "digital-houses", "mode": "yaml", "title": "DigitalHouses"})
        self.transport.config = {"views": [{"path": "dh_pve_agent", "title": "Existing"}]}
        self.assertEqual(self.publisher.sync()["state"], "YAML registered")
        self.assertFalse(any(c[0] == "lovelace/config/save" for c in self.transport.calls))

    def test_alternate_legacy_yaml_dashboard_not_duplicated(self):
        self.view("10_pve.yaml", "dh_pve_agent")
        self.transport.dashboards.append(
            {"url_path": "digitalhouses", "mode": "yaml", "title": "DigitalHouses"})
        self.transport.configs["digitalhouses"] = {
            "views": [{"path": "dh_pve_agent", "title": "Existing"}]}
        result = self.publisher.sync()
        self.assertEqual(result["state"], "YAML registered", result["issues"])
        self.assertEqual(result["url"], "/digitalhouses/")
        self.assertEqual([row for row in self.transport.dashboards
                          if row["url_path"] == URL_PATH], [])

    def test_destination_save_failure_does_not_remove_old_managed_view(self):
        self.view("10_pve.yaml", "dh_pve_agent")
        self.publisher.sync()
        self.transport.save_fail = True
        result = self.publisher.sync({"dh_pve_agent": "dh-system"})
        self.assertEqual(result["state"], "Partial", result["issues"])
        self.assertEqual(self.transport.config["views"][0]["path"], "dh_pve_agent")

    def test_yaml_dashboard_must_really_contain_the_views(self):
        self.view("10_pve_proxmox.yaml", "dh_pve_agent")
        self.transport.dashboards.append(
            {"url_path": "digital-houses", "mode": "yaml", "title": "DigitalHouses"})
        self.transport.config = {"views": [{"path": "other", "title": "Other"}]}
        result = self.publisher.sync()
        self.assertEqual(result["state"], "Partial")
        self.assertIn("does not include", result["issues"][0])

    def test_no_published_views_does_not_create_empty_panel(self):
        self.assertEqual(self.publisher.sync()["state"], "No published views")
        self.assertFalse(self.transport.calls)

    def test_creates_two_named_panels_and_preserves_separate_views(self):
        self.view("10_pve.yaml", "dh_pve_agent")
        self.view("11_ups.yaml", "dh_pve_agent_ups")
        self.view("30_climate.yaml", "dh_climate_room")
        result = self.publisher.sync({
            "dh_pve_agent": "dh-system",
            "dh_pve_agent_ups": "dh-system",
            "dh_climate_room": "dh-climate",
        })
        self.assertEqual(result["state"], "Updated", result["issues"])
        self.assertEqual({row["slug"] for row in result["dashboards"]},
                         {"dh-system", "dh-climate"})
        self.assertEqual([row["path"] for row in self.transport.configs["dh-system"]["views"]],
                         ["dh_pve_agent", "dh_pve_agent_ups"])
        self.assertEqual([row["path"] for row in self.transport.configs["dh-climate"]["views"]],
                         ["dh_climate_room"])
        again = self.publisher.sync({
            "dh_pve_agent": "dh-system", "dh_pve_agent_ups": "dh-system",
            "dh_climate_room": "dh-climate",
        })
        self.assertEqual(again["state"], "Current", again["issues"])
        self.assertEqual([kind for kind, _ in self.transport.calls].count(
            "lovelace/dashboards/create"), 2)

    def test_migrates_legacy_views_after_target_is_saved(self):
        self.view("10_pve.yaml", "dh_pve_agent")
        self.view("11_ups.yaml", "dh_pve_agent_ups")
        self.view("12_manual.yaml", "manual_view")
        self.publisher.sync()
        self.transport.config["views"].append({"path": "user_view", "title": "Keep me"})
        # Simulate persisted single-panel ownership from version 0.4.4.
        legacy = self.data / "dashboard-managed.json"
        current_marker = self.data / "dashboard-managed/digital-houses.json"
        legacy.write_bytes(current_marker.read_bytes())
        current_marker.unlink()
        result = self.publisher.sync({
            "dh_pve_agent": "dh-system", "dh_pve_agent_ups": "dh-system",
            "manual_view": "digital-houses",
        })
        self.assertEqual(result["state"], "Updated", result["issues"])
        self.assertEqual([row["path"] for row in self.transport.configs["dh-system"]["views"]],
                         ["dh_pve_agent", "dh_pve_agent_ups"])
        self.assertEqual([row["path"] for row in self.transport.config["views"]],
                         ["manual_view", "user_view"])
        self.assertEqual(result["issues"], [])
        self.assertEqual(self.publisher.sync({
            "dh_pve_agent": "dh-system", "dh_pve_agent_ups": "dh-system",
            "manual_view": "digital-houses",
        })["state"], "Current")

    def test_failed_destination_does_not_remove_legacy_view(self):
        self.view("10_pve.yaml", "dh_pve_agent")
        self.publisher.sync()
        self.transport.dashboards.append(
            {"url_path": "dh-system", "mode": "storage", "title": "Unmanaged"})
        result = self.publisher.sync({"dh_pve_agent": "dh-system"})
        self.assertEqual(result["state"], "Partial")
        self.assertIn("not owned", result["issues"][0])
        self.assertEqual(self.transport.config["views"][0]["path"], "dh_pve_agent")

    def test_two_products_share_system_panel(self):
        self.view("10_pve.yaml", "dh_pve_agent")
        self.view("12_plex.yaml", "dh-plex-agent")
        result = self.publisher.sync({"dh_pve_agent": "dh-system",
                                      "dh-plex-agent": "dh-system"})
        self.assertEqual(result["state"], "Updated")
        self.assertEqual(len(self.transport.configs["dh-system"]["views"]), 2)
        self.assertEqual(len([x for x in self.transport.dashboards
                              if x.get("url_path") == "dh-system"]), 1)

    def test_legacy_without_dashboard_stays_in_original_panel(self):
        self.view("10_pve.yaml", "dh_pve_agent")
        self.view("12_legacy.yaml", "legacy")
        result = self.publisher.sync({"dh_pve_agent": "dh-system"})
        self.assertEqual(result["state"], "Updated", result["issues"])
        self.assertEqual([row["path"] for row in self.transport.config["views"]],
                         ["legacy"])

    def test_one_dashboard_failure_does_not_block_other_panels(self):
        self.view("10_pve.yaml", "dh_pve_agent")
        self.view("30_climate.yaml", "dh_climate")
        self.transport.dashboards.append(
            {"url_path": "dh-climate", "mode": "storage", "title": "Personal"})
        report = self.publisher.sync({"dh_pve_agent": "dh-system",
                                      "dh_climate": "dh-climate"})
        self.assertEqual(report["state"], "Partial")
        self.assertEqual(self.transport.configs["dh-system"]["views"][0]["path"],
                         "dh_pve_agent")
        self.assertEqual(len(report["issues"]), 1)

    def test_route_absent_keeps_previous_managed_panel(self):
        self.view("10_pve.yaml", "dh_pve_agent")
        self.publisher.sync({"dh_pve_agent": "dh-system"})
        report = self.publisher.sync()
        self.assertEqual(report["state"], "Current", report["issues"])
        self.assertIsNone(self.transport.config)

    def test_dashboard_error_propagates_into_sync_status(self):
        self.transport.create_fail = True
        app = AutoSync(self.root, self.data, backend=FakeBackend(), publisher=self.publisher)
        (self.root / "configuration.yaml").write_text(
            "homeassistant:\n  packages: !include_dir_merge_named packages/\n")
        result = app.sync(CLAIMS)
        self.assertEqual(result["state"], "Partial")
        self.assertEqual(result["updated"], 2)
        self.assertTrue(any("creation failed" in issue for issue in result["issues"]))

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
