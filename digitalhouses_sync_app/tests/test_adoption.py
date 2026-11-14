import json
import tempfile
import unittest
from pathlib import Path

from adoption import AdoptionError, assess, record_recorder, storage_matches

VIEW = """# DH-View: dh_plex_agent
# DH-View-Version: 1.0.0
# DH-Compatible-Agent: >=0.8.17,<0.8.18
type: sections
title: Plex
path: dh-plex-agent
sections: []
"""
PACKAGE = """# DH-Package: dh_app_plex_monitoring_package
# DH-Package-Version: 1.0.0
# DH-Compatible-Agent: >=0.8.17,<0.8.18
dh_app_plex_monitoring_package:
  recorder:
    include:
      entities:
        - sensor.dh_plex_agent_cpu
"""


class AdoptionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / "homeassistant"
        self.data = self.root / "data"
        (self.home / "packages" / "DH").mkdir(parents=True)
        (self.home / ".storage").mkdir()
        self.data.mkdir()
        (self.home / "configuration.yaml").write_text(
            "homeassistant:\n  packages: !include_dir_merge_named packages/\n"
        )
        self.installed = self.home / "packages" / "DH" / "dh_plex_app_package.yaml"
        self.installed.write_text(PACKAGE.split("\n", 3)[3])

    def put_storage(self, views):
        path = self.home / ".storage" / "lovelace.dashboard_system"
        path.write_text(json.dumps({
            "version": 1, "key": "lovelace.dashboard_system",
            "data": {"config": {"title": "Storage", "views": views}},
        }))
        return path

    def test_match_read_only_without_mutation(self):
        import yaml
        storage = self.put_storage([yaml.safe_load(VIEW)])
        before = (storage.read_bytes(), self.installed.read_bytes())
        report = assess(self.home, VIEW, PACKAGE)
        self.assertEqual(report["view"]["status"], "blocked_identical_storage_view")
        self.assertEqual(report["recorder"]["status"], "exact_existing_package")
        self.assertFalse(report["automatic_apply_allowed"])
        self.assertEqual(before, (storage.read_bytes(), self.installed.read_bytes()))
        self.assertFalse((self.data / "plex_recorder_adoption.json").exists())

    def test_manual_receipt_only_and_idempotence(self):
        report = assess(self.home, VIEW, PACKAGE)
        before = self.installed.read_bytes()
        receipt = record_recorder(self.home, self.data, report, PACKAGE)
        self.assertFalse(receipt["live_agent_version_verified"])
        self.assertEqual(receipt["status"], "recorded_only_no_ha_writes")
        self.assertEqual(receipt, record_recorder(self.home, self.data, report, PACKAGE))
        self.assertEqual(before, self.installed.read_bytes())

    def test_changed_file_refused(self):
        report = assess(self.home, VIEW, PACKAGE)
        self.installed.write_text("other: yes\n")
        with self.assertRaises(AdoptionError):
            record_recorder(self.home, self.data, report, PACKAGE)

    def test_conflicting_package_blocks_receipt(self):
        self.installed.write_text(
            "dh_app_plex_monitoring_package:\n  recorder:\n    include: {}\n"
        )
        report = assess(self.home, VIEW, PACKAGE)
        self.assertEqual(report["recorder"]["status"], "blocked_different_package")
        with self.assertRaises(AdoptionError):
            record_recorder(self.home, self.data, report, PACKAGE)

    def test_duplicate_package_key_blocked(self):
        second = self.home / "packages" / "DH" / "another.yaml"
        second.write_text(self.installed.read_text())
        report = assess(self.home, VIEW, PACKAGE)
        self.assertEqual(report["recorder"]["status"], "blocked_duplicate_package_key")

    def test_missing_or_unsupported_loader_blocks(self):
        (self.home / "configuration.yaml").write_text(
            "homeassistant:\n  packages: !include_dir_named packages/\n"
        )
        self.assertEqual(
            assess(self.home, VIEW, PACKAGE)["recorder"]["status"],
            "blocked_unverified_package_loader",
        )

    def test_storage_content_difference_blocks(self):
        self.put_storage([{"title": "Plex", "path": "dh-plex-agent", "type": "sections"}])
        report = assess(self.home, VIEW, PACKAGE)
        self.assertEqual(report["view"]["status"], "blocked_different_storage_view")

    def test_multiple_storage_view_matches_block(self):
        import yaml
        view = yaml.safe_load(VIEW)
        self.put_storage([view, view])
        self.assertEqual(
            assess(self.home, VIEW, PACKAGE)["view"]["status"],
            "blocked_duplicate_storage_views",
        )

    def test_symlink_package_refused(self):
        other = self.root / "other.yaml"
        other.write_text(self.installed.read_text())
        self.installed.unlink()
        self.installed.symlink_to(other)
        with self.assertRaises(AdoptionError):
            assess(self.home, VIEW, PACKAGE)

    def test_malformed_storage_blocks(self):
        (self.home / ".storage" / "lovelace.dashboard_system").write_text("invalid")
        with self.assertRaises(AdoptionError):
            assess(self.home, VIEW, PACKAGE)

    def test_receipt_conflict_not_overwritten(self):
        report = assess(self.home, VIEW, PACKAGE)
        receipt = record_recorder(self.home, self.data, report, PACKAGE)
        receipt_path = self.data / "plex_recorder_adoption.json"
        receipt_path.write_text('{"arbitrary": true}')
        with self.assertRaises(AdoptionError):
            record_recorder(self.home, self.data, report, PACKAGE)
        self.assertEqual(receipt_path.read_text(), '{"arbitrary": true}')


if __name__ == "__main__":
    unittest.main()
