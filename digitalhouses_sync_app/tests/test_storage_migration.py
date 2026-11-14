"""No live Home Assistant is modified by these deterministic migration tests."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

import yaml

from storage_migration import MigrationError, PlexMigration

VIEW = """# DH-View: dh_plex_agent
# DH-View-Version: 1.0.0
# DH-View-Date: 2026-11-14
# DH-Compatible-Agent: >=0.8.17,<0.8.18
type: sections
title: Plex
path: dh-plex-agent
sections: []
"""
PLEX = yaml.safe_load(VIEW)
OTHER = {"title": "Other", "path": "other", "cards": []}


class FakeHA:
    def __init__(self):
        self.storage = {"title": "Storage", "views": [OTHER, copy.deepcopy(PLEX)]}
        self.disk = copy.deepcopy(self.storage)
        self.target = {"title": "DigitalHouses", "views": []}
        self.config_valid = True
        self.persist = True
        self.calls = []

    def read_storage(self, url_path):
        assert url_path == "dashboard-system"
        return copy.deepcopy(self.storage)

    def save_storage(self, url_path, value):
        assert url_path == "dashboard-system"
        self.calls.append("save")
        self.storage = copy.deepcopy(value)
        if self.persist:
            self.disk = copy.deepcopy(value)

    def read_persisted_storage(self, url_path):
        return copy.deepcopy(self.disk)

    def read_target_yaml_dashboard(self, url_path):
        assert url_path == "digital-houses"
        return copy.deepcopy(self.target)

    def check_config(self):
        self.calls.append("check")
        return self.config_valid


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.home = root / "home"
        self.data = root / "data"
        self.home.mkdir()
        self.data.mkdir()
        self.views = self.home / "dashboards/dh/views"
        self.views.mkdir(parents=True)
        (self.home / "dashboards/dh/ui.yaml").write_text(
            "title: DigitalHouses\nviews: !include_dir_list views\n"
        )
        self.api = FakeHA()
        self.engine = PlexMigration(
            self.home, self.data, self.api, source_url_path="dashboard-system"
        )

    def stage(self):
        return self.engine.stage(VIEW, runtime_version="0.8.17", confirm=True)

    def test_stage_never_edits_storage(self):
        original = copy.deepcopy(self.api.storage)
        self.assertEqual(self.stage()["phase"], "staged")
        self.assertEqual(self.api.storage, original)
        self.assertEqual(self.api.disk, original)
        self.assertTrue((self.views / "10_plex.yaml").is_file())

    def test_cutover_requires_explicit_visual_confirmation(self):
        self.stage()
        with self.assertRaises(MigrationError):
            self.engine.cutover(VIEW, confirm_rendered=False)
        self.assertEqual(len(self.api.storage["views"]), 2)

    def test_full_stage_cutover_rollback_preserves_other_views(self):
        self.stage()
        self.api.target["views"] = [copy.deepcopy(PLEX)]
        self.assertEqual(
            self.engine.cutover(VIEW, confirm_rendered=True)["phase"], "cutover"
        )
        self.assertEqual(self.api.storage["views"], [OTHER])
        self.assertEqual(self.api.disk["views"], [OTHER])
        self.assertEqual(
            self.engine.rollback(confirm=True)["phase"], "rolled_back"
        )
        self.assertEqual(self.api.storage["views"], [OTHER, PLEX])
        self.assertFalse((self.views / "10_plex.yaml").exists())

    def test_mismatched_storage_refused(self):
        self.api.storage["views"][1]["title"] = "Locally edited"
        self.api.disk = copy.deepcopy(self.api.storage)
        with self.assertRaises(MigrationError):
            self.stage()

    def test_duplicate_storage_view_refused(self):
        self.api.storage["views"].append(copy.deepcopy(PLEX))
        self.api.disk = copy.deepcopy(self.api.storage)
        with self.assertRaises(MigrationError):
            self.stage()

    def test_preexisting_target_file_refused(self):
        file = self.views / "10_plex.yaml"
        file.write_text("Existing work\n")
        with self.assertRaises(MigrationError):
            self.stage()
        self.assertEqual(file.read_text(), "Existing work\n")

    def test_preexisting_alternative_path_refused(self):
        (self.views / "99_custom.yaml").write_text(
            "title: duplicate\npath: dh-plex-agent\n"
        )
        with self.assertRaises(MigrationError):
            self.stage()

    def test_wrong_agent_version_refused(self):
        with self.assertRaises(MigrationError):
            self.engine.stage(VIEW, runtime_version="0.8.18", confirm=True)

    def test_unregistered_ui_refused(self):
        (self.home / "dashboards/dh/ui.yaml").unlink()
        with self.assertRaises(MigrationError):
            self.stage()

    def test_invalid_config_reverts_new_file(self):
        self.api.config_valid = False
        with self.assertRaises(MigrationError):
            self.stage()
        self.assertFalse((self.views / "10_plex.yaml").exists())

    def test_stale_storage_after_stage_refused(self):
        self.stage()
        self.api.storage["views"].append({"title": "New", "path": "new"})
        self.api.disk = copy.deepcopy(self.api.storage)
        self.api.target["views"] = [copy.deepcopy(PLEX)]
        with self.assertRaises(MigrationError):
            self.engine.cutover(VIEW, confirm_rendered=True)
        self.assertEqual(len(self.api.storage["views"]), 3)

    def test_stale_disk_after_api_save_causes_failure(self):
        self.stage()
        self.api.target["views"] = [copy.deepcopy(PLEX)]
        self.api.persist = False
        with self.assertRaises(MigrationError):
            self.engine.cutover(VIEW, confirm_rendered=True)
        self.assertNotEqual(
            self.api.storage["views"], [OTHER]
        )  # API state restored, even though persistence validation failed
        self.assertEqual(len(self.api.storage["views"]), 2)

    def test_rollback_requires_confirmation_and_refuses_local_edits(self):
        self.stage()
        with self.assertRaises(MigrationError):
            self.engine.rollback(confirm=False)
        (self.views / "10_plex.yaml").write_text("user change\n")
        with self.assertRaises(MigrationError):
            self.engine.rollback(confirm=True)
        self.assertEqual((self.views / "10_plex.yaml").read_text(), "user change\n")


if __name__ == "__main__":
    unittest.main()
