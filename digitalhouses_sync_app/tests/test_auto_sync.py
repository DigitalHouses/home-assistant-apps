"""End-to-end tests for MQTT products, GitHub panels and HA packages."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from auto_sync import AutoSync, configured_packages, package_identity, package_keys
from panel_config import PANEL_DIRECTORY, PANEL_REPOSITORY

REPO = "https://github.com/DigitalHouses/any-repo"
CLAIMS = {"example/default": {"repository": REPO, "product_id": "example",
          "product_path": "example", "version": "9999.0"}}
VIEW = b"title: First\npath: first\ntype: sections\nsections: []\n"
PACKAGE = b"dh_example_package:\n  recorder:\n    include:\n      entities:\n        - sensor.example\n"
PACKAGE_NEW = PACKAGE.replace(b"sensor.example", b"sensor.more")
PANEL = (b"title: DH System\nrequire_admin: true\n"
         b"views:\n  - product: example\n    path: first\n")


class FakeBackend:
    def __init__(self):
        self.raw = {
            "example/dashboards/ru/10_first.yaml": VIEW,
            "example/packages/common/dh_example_package.yaml": PACKAGE,
            PANEL_DIRECTORY + "/dh-system.yaml": PANEL,
        }
        self.revisions = []

    def invalidate(self):
        self.invalidate_calls = getattr(self, "invalidate_calls", 0) + 1

    def resolve_revision(self, repo):
        self.revisions.append(repo)
        return "a" * 40, "main"

    def list_yaml(self, repo, folder, commit):
        return [{"name": p.split("/")[-1], "path": p, "type": "file"}
                for p in sorted(self.raw) if p.startswith(folder + "/")
                and "/" not in p[len(folder) + 1:]]

    def read_view(self, repo, path, commit):
        return self.raw[path]


class RecordingPublisher:
    def __init__(self):
        self.calls = []

    def sync(self, panels, sources):
        self.calls.append((panels, sources))
        return {"state": "Updated", "url": "/dh-system/",
                "dashboards": [], "issues": []}


class AutomaticSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        home = Path(self.tmp.name) / "homeassistant"
        home.mkdir()
        self.root = home
        self.data = Path(self.tmp.name) / "journal"
        (home / "configuration.yaml").write_text(
            "homeassistant:\n  packages: !include_dir_merge_named packages/\n")
        self.backend = FakeBackend()
        self.publisher = RecordingPublisher()
        self.app = AutoSync(home, self.data, backend=self.backend,
                            publisher=self.publisher)

    def test_first_install_and_idempotent_second_pass(self):
        first = self.app.sync(CLAIMS)
        self.assertEqual(first["state"], "OK", first["issues"])
        self.assertEqual(first["updated"], 1)  # Package, not local view copy.
        self.assertEqual((self.root / "packages/dh/dh_example_package.yaml").read_bytes(), PACKAGE)
        self.assertFalse((self.root / "dashboards").exists())
        self.assertEqual(self.publisher.calls[-1][0][0]["slug"], "dh-system")
        self.assertIn(("example", "first"), self.publisher.calls[-1][1])
        second = self.app.sync(CLAIMS)
        self.assertEqual(second["updated"], 0)
        self.assertEqual(second["unchanged"], 1)

    def test_report_includes_packages_views_and_panels(self):
        from dashboard_runtime import DashboardPublisher
        from test_dashboard_runtime import FakeWS
        self.app.publisher = DashboardPublisher(self.root, self.data, transport=FakeWS())
        first = self.app.sync(CLAIMS)
        self.assertEqual(first["updated"], 3, first["issues"])
        self.assertEqual({r["kind"] for r in first["resources"]}, {"Package", "View", "Dashboard"})
        second = self.app.sync(CLAIMS)
        self.assertEqual(second["updated"], 0)
        self.assertEqual(second["unchanged"], 3)
        self.backend.raw["example/dashboards/ru/10_first.yaml"] = VIEW.replace(b"First", b"Second")
        third = self.app.sync(CLAIMS, refresh=True)
        self.assertEqual(third["updated"], 1)
        self.assertEqual(third["unchanged"], 2)
        self.assertEqual(third["trigger"], "manual")
        self.assertTrue(third["last_run"])

    def test_one_toast_for_changes_and_attention_only(self):
        from dashboard_runtime import DashboardPublisher
        from test_dashboard_runtime import FakeWS
        from event_journal import EventJournal
        journal = EventJournal(self.data.parent / "toast.db")
        self.addCleanup(journal.backend.close)
        self.app.journal = journal
        ws = FakeWS()
        self.app.publisher = DashboardPublisher(self.root, self.data, transport=ws, journal=journal)
        first = self.app.sync(CLAIMS)
        rows = journal.backend.toast_snapshot(0)["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["code"], "sync_result")
        self.assertEqual({k:rows[0]["params"][k] for k in ("views","packages","dashboards")}, {"views":1,"packages":1,"dashboards":1})
        self.assertEqual(first["updated"], 3)
        cursor = journal.backend.toast_snapshot()["cursor"]
        self.app.sync(CLAIMS)
        self.app.sync(CLAIMS, refresh=True)
        self.assertEqual(journal.backend.toast_snapshot(cursor)["rows"], [])
        ws.fail_save = True
        self.backend.raw["example/dashboards/ru/10_first.yaml"] = VIEW.replace(b"First", b"Changed")
        self.app.sync(CLAIMS)
        rows = journal.backend.toast_snapshot(cursor)["rows"]
        self.assertEqual([r["code"] for r in rows], ["sync_partial"])
        self.assertEqual(rows[0]["level"], "warning")
        cursor = journal.backend.toast_snapshot()["cursor"]
        self.app.sync(CLAIMS)
        self.assertEqual(journal.backend.toast_snapshot(cursor)["rows"], [])
        self.app._check_root = lambda: (_ for _ in ()).throw(ValueError("test failure"))
        self.app.sync(CLAIMS)
        rows = journal.backend.toast_snapshot(cursor)["rows"]
        self.assertEqual([r["code"] for r in rows], ["sync_failed"])
        self.assertEqual(rows[0]["level"], "error")
        self.assertTrue(any(r["code"] == "package_updated" for r in journal.backend.snapshot()["rows"]))

    def test_manual_refresh_runs_same_autosync_and_invalidates_git(self):
        automatic = self.app.sync(CLAIMS)
        self.assertEqual(automatic["updated"], 1)
        self.assertEqual(getattr(self.backend, "invalidate_calls", 0), 0)
        manual = self.app.sync(CLAIMS, refresh=True)
        self.assertEqual(manual["updated"], 0)
        self.assertEqual(manual["unchanged"], 1)
        self.assertEqual(self.backend.invalidate_calls, 1)
        self.assertEqual(self.publisher.calls[-1][0][0]["slug"], "dh-system")
        self.backend.raw["example/packages/common/dh_example_package.yaml"] = PACKAGE_NEW
        updated = self.app.sync(CLAIMS, refresh=True)
        self.assertEqual(updated["updated"], 1)
        self.assertEqual(self.backend.invalidate_calls, 2)
        self.assertEqual((self.root / "packages/dh/dh_example_package.yaml").read_bytes(), PACKAGE_NEW)

    def test_mqtt_dashboard_is_completely_ignored(self):
        claims = {"example/old": {**CLAIMS["example/default"], "dashboard": "dh-legacy"},
                  "example/new": {**CLAIMS["example/default"], "dashboard": "dh-system"}}
        report = self.app.sync(claims)
        self.assertEqual(report["state"], "OK", report["issues"])
        self.assertEqual([p["slug"] for p in self.publisher.calls[-1][0]], ["dh-system"])
        self.assertEqual(list(self.publisher.calls[-1][1]), [("example", "first")])

    def test_empty_mqtt_registry_never_invents_products_from_yaml(self):
        old = self.root / "dashboards/dh/views/10_old.yaml"
        old.parent.mkdir(parents=True)
        old.write_bytes(VIEW)
        report = self.app.sync({})
        self.assertEqual(report["state"], "OK", report["issues"])
        self.assertEqual(report["updated"], 0)
        self.assertEqual(self.publisher.calls[-1][1], {})
        self.assertEqual(old.read_bytes(), VIEW)

    def test_same_view_path_from_different_products_is_distinct(self):
        self.backend.raw["other/dashboards/ru/10_first.yaml"] = VIEW
        other = {"other/default": {"repository": REPO, "product_id": "other",
                                   "product_path": "other"}}
        resources, issues = self.app._published({**CLAIMS, **other})
        self.assertEqual(issues, [])
        self.assertEqual(len([r for r in resources if r["kind"] == "view"]), 2)
        self.app.sync({**CLAIMS, **other})
        keys = self.publisher.calls[-1][1].keys()
        self.assertIn(("example", "first"), keys)
        self.assertIn(("other", "first"), keys)

    def test_panel_files_can_be_modified_without_product_version_change(self):
        self.app.sync(CLAIMS)
        self.backend.raw[PANEL_DIRECTORY + "/dh-system.yaml"] = (
            b"title: Updated System\nrequire_admin: true\nviews: []\n")
        self.app.sync(CLAIMS)
        self.assertEqual(self.publisher.calls[-1][0][0]["title"], "Updated System")
        self.assertEqual(self.publisher.calls[-1][0][0]["views"], [])

    def test_missing_product_view_is_normal(self):
        del self.backend.raw["example/dashboards/ru/10_first.yaml"]
        self.app.sync(CLAIMS)
        self.assertEqual(self.publisher.calls[-1][1], {})
        self.assertEqual(self.app.status()["state"], "OK")

    def test_package_updates_do_not_depend_on_version(self):
        self.app.sync(CLAIMS)
        self.backend.raw["example/packages/common/dh_example_package.yaml"] = PACKAGE_NEW
        result = self.app.sync(CLAIMS)
        self.assertEqual(result["updated"], 1, result["issues"])
        self.assertEqual((self.root / "packages/dh/dh_example_package.yaml").read_bytes(),
                         PACKAGE_NEW)

    def test_missing_loader_is_configured_without_confirmation(self):
        config = self.root / "configuration.yaml"
        config.write_text("default_config:\n# custom\nhomeassistant:\n  name: Home\n")
        calls = []
        self.app.reloader = lambda: calls.append("reload")
        result = self.app.sync(CLAIMS)
        self.assertEqual(result["state"], "OK", result["issues"])
        self.assertEqual(result["packages"]["reload"], "Requested")
        self.assertEqual(calls, ["reload"])
        self.assertIn("name: Home", config.read_text())
        self.assertIn("packages: !include_dir_merge_named packages/", config.read_text())

    def test_conflicting_package_loader_is_left_untouched(self):
        config = self.root / "configuration.yaml"
        old = "homeassistant:\n  packages: !include_dir_named packages/\n"
        config.write_text(old)
        result = self.app.sync(CLAIMS)
        self.assertEqual(result["state"], "Error", result["issues"])
        self.assertEqual(config.read_text(), old)
        self.assertFalse((self.root / "packages/dh/dh_example_package.yaml").exists())

    def test_old_local_view_never_migrated_or_deleted(self):
        old = self.root / "dashboards/dh/views/legacy.yaml"
        old.parent.mkdir(parents=True)
        old.write_bytes(VIEW)
        self.app.sync(CLAIMS)
        self.assertEqual(old.read_bytes(), VIEW)
        self.assertFalse((old.parent / "10_first.yaml").exists())

    def test_bad_github_owner_is_not_admitted(self):
        claim = {"bad/default": {**CLAIMS["example/default"],
                 "repository": "https://github.com/OtherOwner/repo"}}
        report = self.app.sync(claim)
        self.assertTrue(report["issues"])
        self.assertEqual(self.publisher.calls[-1][1], {})

    def test_other_package_and_local_file_is_preserved(self):
        own = self.root / "packages/private.yaml"
        own.parent.mkdir(parents=True, exist_ok=True)
        own.write_text("user_package:\n  script: {}\n")
        self.app.sync(CLAIMS)
        self.assertIn("user_package", own.read_text())

    def test_repeated_instances_do_not_duplicate_files(self):
        value = CLAIMS["example/default"]
        self.app.sync({"example/one": value, "example/two": value})
        self.assertEqual(len(self.publisher.calls[-1][1]), 1)
        self.assertEqual(len(list((self.root / "packages/dh").glob("*.yaml"))), 1)

    def test_panel_repository_uses_digitalhouses_owner(self):
        self.app.sync(CLAIMS)
        self.assertIn(PANEL_REPOSITORY, self.backend.revisions)

    def test_package_identity_and_loader_parsing(self):
        self.assertEqual(package_identity(PACKAGE), "dh_example_package")
        self.assertEqual(package_keys(PACKAGE), ["dh_example_package"])
        self.assertIsNone(configured_packages(
            b"homeassistant:\n  packages: !include_dir_merge_named packages/\n"))


if __name__ == "__main__":
    unittest.main()
