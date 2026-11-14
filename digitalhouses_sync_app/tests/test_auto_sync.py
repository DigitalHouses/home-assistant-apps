"""End-to-end tests: autonomous dashboard and package synchronization."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from auto_sync import AutoSync, package_identity, package_keys

REPO = "https://github.com/DigitalHouses/any-repo"
CLAIMS = {
    "example/default": {
        "repository": REPO, "product_id": "example",
        "product_path": "example", "version": "9999.0",
    },
}
VIEW = b"title: First\npath: first\ntype: sections\nsections: []\n"
VIEW_NEW = b"title: First\npath: first\ntype: sections\nsections: []\nicon: mdi:home\n"
PACKAGE = b"dh_example_package:\n  recorder:\n    include:\n      entities:\n        - sensor.example\n"
PACKAGE_NEW = b"# DH-Package-Version: 2.0.0\ndh_example_package:\n  recorder:\n    include:\n      entities:\n        - sensor.example\n        - sensor.more\n"


class FakeBackend:
    def __init__(self):
        self.raw = {
            "example/dashboards/ru/10_first.yaml": VIEW,
            "example/packages/common/dh_example_package.yaml": PACKAGE,
        }
        self.calls = 0

    def resolve_revision(self, repo):
        self.calls += 1
        return "a" * 40, "main"

    def list_yaml(self, repo, folder, commit):
        return [{"name": path.split("/")[-1], "path": path, "type": "file"}
                for path in self.raw if path.startswith(folder + "/")
                and "/" not in path[len(folder) + 1:]]

    def read_view(self, repo, path, commit):
        return self.raw[path]


class AutomaticSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.root = base / "homeassistant"
        self.views = self.root / "dashboards/dh/views"
        self.views.mkdir(parents=True)
        (self.root / "dashboards/dh/ui.yaml").write_text(
            "title: DigitalHouses\nviews: !include_dir_list views/\n")
        (self.root / "configuration.yaml").write_text(
            "homeassistant:\n  packages: !include_dir_merge_named packages/\n")
        (self.root / ".storage").mkdir()
        self.backend = FakeBackend()
        self.app = AutoSync(self.root, base / "journal", backend=self.backend)

    def test_zero_click_install_and_second_pass_no_changes(self):
        first = self.app.sync(CLAIMS)
        self.assertEqual(first["state"], "OK", first["issues"])
        self.assertEqual(first["updated"], 2)
        self.assertEqual((self.views / "10_first.yaml").read_bytes(), VIEW)
        self.assertEqual((self.root / "packages/dh/dh_example_package.yaml").read_bytes(),
                         PACKAGE)
        second = self.app.sync(CLAIMS)
        self.assertEqual(second["updated"], 0)
        self.assertEqual(second["unchanged"], 2)
        self.assertEqual(len(list((self.root / "packages").rglob("*.yaml"))), 1)

    def test_replace_existing_views_and_packages_in_original_locations(self):
        old_view = VIEW + b"# local old\n"
        old_package = PACKAGE + b"# local old\n"
        (self.views / "99_existing.yaml").write_bytes(old_view)
        folder = self.root / "packages/Global/System"
        folder.mkdir(parents=True)
        local = folder / "my_existing.yaml"
        local.write_bytes(old_package)
        report = self.app.sync(CLAIMS)
        self.assertEqual(report["updated"], 2, report["issues"])
        self.assertEqual((self.views / "99_existing.yaml").read_bytes(), VIEW)
        self.assertEqual(local.read_bytes(), PACKAGE)
        self.assertFalse((self.views / "10_first.yaml").exists())
        self.assertFalse((self.root / "packages/dh/dh_example_package.yaml").exists())
        backups = list((self.app.data).glob("tx-*/original.yaml"))
        self.assertEqual(sorted(b.read_bytes() for b in backups),
                         sorted([old_view, old_package]))

    def test_package_and_dashboard_update_without_app_version_change(self):
        self.app.sync(CLAIMS)
        self.backend.raw["example/dashboards/ru/10_first.yaml"] = VIEW_NEW
        self.backend.raw["example/packages/common/dh_example_package.yaml"] = PACKAGE_NEW
        report = self.app.sync(CLAIMS)
        self.assertEqual(report["updated"], 2, report["issues"])
        self.assertEqual((self.views / "10_first.yaml").read_bytes(), VIEW_NEW)
        self.assertEqual((self.root / "packages/dh/dh_example_package.yaml").read_bytes(),
                         PACKAGE_NEW)

    def test_reject_duplicate_existing_package_key(self):
        folder = self.root / "packages/Local"
        folder.mkdir(parents=True)
        for i in range(2):
            (folder / (str(i) + ".yaml")).write_bytes(PACKAGE)
        report = self.app.sync(CLAIMS)
        self.assertEqual(report["updated"], 1)
        self.assertIn("Duplicate local package key", report["issues"][0])
        self.assertEqual(len(list(folder.glob("*.yaml"))), 2)

    def test_storage_collision_skips_view_not_package(self):
        store = {"data": {"config": {"views": [{"path": "first"}]}}}
        (self.root / ".storage/lovelace.dashboard_system").write_text(
            json.dumps(store))
        report = self.app.sync(CLAIMS)
        self.assertEqual(report["updated"], 1, report["issues"])
        self.assertTrue(report["issues"])
        self.assertFalse((self.views / "10_first.yaml").exists())
        self.assertTrue((self.root / "packages/dh/dh_example_package.yaml").exists())

    def test_foreign_github_owner_not_admitted(self):
        claim = {"example/default": {
            **CLAIMS["example/default"],
            "repository": "https://github.com/SomeoneElse/any-repo",
        }}
        report = self.app.sync(claim)
        self.assertEqual(report["updated"], 0)
        self.assertTrue(report["issues"])
        self.assertEqual(self.backend.calls, 0)

    def test_local_multi_key_package_is_not_erased(self):
        folder = self.root / "packages/Global"
        folder.mkdir(parents=True)
        local = folder / "shared.yaml"
        content = PACKAGE + b"\nother_package:\n  input_boolean:\n    test:\n      name: Test\n"
        local.write_bytes(content)
        report = self.app.sync(CLAIMS)
        self.assertEqual(report["updated"], 1)
        self.assertTrue(report["issues"])
        self.assertEqual(local.read_bytes(), content)
        self.assertEqual(package_keys(content),
                         ["dh_example_package", "other_package"])

    def test_user_custom_notification_not_touched_when_not_published(self):
        folder = self.root / "packages/Global"
        folder.mkdir(parents=True)
        local = folder / "notification.yaml"
        content = b"dh_notification_local:\n  automation:\n    - id: custom\n      alias: keep\n"
        local.write_bytes(content)
        report = self.app.sync(CLAIMS)
        self.assertEqual(report["updated"], 2, report["issues"])
        self.assertEqual(local.read_bytes(), content)

    def test_header_version_never_blocks_source(self):
        self.backend.raw["example/packages/common/dh_example_package.yaml"] = (
            b"# DH-Compatible-Agent: >=9999,<10000\n" + PACKAGE
        )
        result = self.app.sync(CLAIMS)
        self.assertEqual(result["updated"], 2, result["issues"])

    def test_recover_power_loss_after_atomic_write(self):
        result = self.app.sync(CLAIMS)
        self.assertEqual(result["updated"], 2)
        file = self.root / "packages/dh/dh_example_package.yaml"
        journal = next(x for x in self.app.data.glob("tx-*")
                       if json.loads((x / "manifest.json").read_text())["path"]
                       == "packages/dh/dh_example_package.yaml")
        manifest = journal / "manifest.json"
        state = json.loads(manifest.read_text())
        state["state"] = "prepared"
        manifest.write_text(json.dumps(state))
        self.app.recover()
        self.assertFalse(file.exists())
        self.assertEqual(json.loads(manifest.read_text())["state"], "recovered")

    def test_absent_resources_do_not_trigger_deletions(self):
        self.app.sync(CLAIMS)
        self.backend.raw.clear()
        report = self.app.sync(CLAIMS)
        self.assertEqual(report["updated"], 0)
        self.assertTrue((self.views / "10_first.yaml").exists())
        self.assertTrue((self.root / "packages/dh/dh_example_package.yaml").exists())


if __name__ == "__main__":
    unittest.main()
