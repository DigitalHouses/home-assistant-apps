"""CORE v3 + Plex: exact-source view delivery with safe restore."""
import copy
import hashlib
import json
import stat
import tempfile
import unittest
from pathlib import Path

from sync_engine import RESOURCES, SyncEngine, SyncError, _digest

VIEWS = {
    "10_pve_proxmox.yaml": ("dh_pve_agent", "Proxmox", "mdi:server"),
    "11_pve_ups.yaml": ("dh_pve_agent_ups", "Электропитание", "mdi:power-plug-battery"),
    "12_plex.yaml": ("dh-plex-agent", "Plex", "mdi:plex"),
}


def view_text(resource, *, legacy=False):
    path, title, icon = VIEWS[resource.target]
    if legacy and resource.target == "11_pve_ups.yaml":
        icon = "mdi:power-plug-battery-outline"
    nav = "" if resource.target == "12_plex.yaml" else (
        "show_icon_and_title: true\n" if legacy else "show_icon_and_title: false\n"
    )
    header = "" if legacy else (
        f"# DH-View: {'dh_pve_agent' if resource.product == 'digitalhouses_pve_agent' else 'dh_plex_agent'}\n"
        "# DH-View-Version: 1.0.0\n"
        f"# DH-Compatible-Agent: {resource.compat}\n\n"
    )
    return (
        header + f"title: {title}\npath: {path}\nicon: {icon}\n" + nav
        + "type: sections\nsections: []\n"
    ).encode()


class FakeAPI:
    def __init__(self, home):
        self.home = home
        self.valid = True
        self.versions_data = {
            "sensor.dh_pve_agent_version": "0.5.88",
            "sensor.dh_plex_agent_version": "0.8.17",
        }
        self.override_view = None

    def versions(self):
        return dict(self.versions_data)

    def dashboard(self):
        import yaml
        views = []
        for f in sorted((self.home / "dashboards/dh/views").glob("*.yaml")):
            views.append(yaml.safe_load(f.read_text()))
        return {"title": "DigitalHouses", "views": views}

    def check_config(self):
        return self.valid


class SyncEngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.home = root / "home"
        self.data = root / "data"
        self.home.joinpath("dashboards/dh/views").mkdir(parents=True)
        self.home.joinpath(".storage").mkdir()
        self.data.mkdir()
        self.home.joinpath("dashboards/dh/ui.yaml").write_text(
            "title: DigitalHouses\nviews: !include_dir_list views/\n"
        )
        self.sources = {x.source: view_text(x) for x in RESOURCES}
        self.initial = {}
        for resource in RESOURCES:
            path = self.home / "dashboards/dh/views" / resource.target
            raw = view_text(resource, legacy=resource.target != "12_plex.yaml")
            path.write_bytes(raw)
            self.initial[resource.target] = raw
        self.api = FakeAPI(self.home)
        self.engine = SyncEngine(
            self.home, self.data, self.api,
            fetcher=lambda r: self.sources[r.source],
        )
        # Unit-test historical snapshots differ from real CORE. Patch only
        # immutable test Resource records, not application production catalog.
        from unittest.mock import patch
        import sync_engine
        import dataclasses
        virtual = tuple(
            dataclasses.replace(r, legacy_sha=_digest(self.initial[r.target]))
            if r.product == "digitalhouses_pve_agent" else r
            for r in RESOURCES
        )
        patcher = patch.object(sync_engine, "RESOURCES", virtual)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_exact_core_v3_plan(self):
        p = self.engine.plan()
        self.assertFalse(p["blocked"])
        self.assertEqual(p["changes"], 2)
        self.assertEqual(
            [x["action"] for x in p["items"]],
            ["replace", "replace", "unchanged"],
        )
        self.assertNotIn("_content", self.engine.public(p)["items"][0])

    def test_confirmed_apply_and_rollback_no_other_files(self):
        extra = self.home / "dashboards/dh/views/01_other.yaml"
        extra.write_text("title: Other\npath: other\n")
        before = extra.read_bytes()
        p = self.engine.plan()
        with self.assertRaises(SyncError):
            self.engine.apply(p["fingerprint"], approved=False)
        result = self.engine.apply(p["fingerprint"], approved=True)
        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["updated"], ["10_pve_proxmox.yaml", "11_pve_ups.yaml"])
        self.assertFalse(result["restart_required"])
        self.assertEqual(extra.read_bytes(), before)
        self.assertEqual(self.engine.plan()["changes"], 0)
        self.engine.rollback(approved=True)
        for name, raw in self.initial.items():
            self.assertEqual(self.home.joinpath("dashboards/dh/views", name).read_bytes(), raw)
        self.assertEqual(extra.read_bytes(), before)

    def test_malformed_external_edit_blocks_batch(self):
        file = self.home / "dashboards/dh/views/10_pve_proxmox.yaml"
        file.write_text("title: Edited\npath: dh_pve_agent\nicon: mdi:server\ntype: sections\nsections: []\n")
        plan = self.engine.plan()
        self.assertTrue(plan["blocked"])
        self.assertEqual(plan["items"][0]["action"], "conflict")
        with self.assertRaises(SyncError):
            self.engine.apply(plan["fingerprint"], approved=True)
        self.assertEqual(file.read_text().splitlines()[0], "title: Edited")

    def test_incompatible_agent_blocks(self):
        self.api.versions_data["sensor.dh_pve_agent_version"] = "0.5.87"
        p = self.engine.plan()
        self.assertTrue(p["blocked"])
        with self.assertRaises(SyncError):
            self.engine.apply(p["fingerprint"], approved=True)

    def test_plan_changed_after_preview_blocks(self):
        p = self.engine.plan()
        self.api.versions_data["sensor.dh_pve_agent_version"] = "0.5.89"
        with self.assertRaisesRegex(SyncError, "Preview expired"):
            self.engine.apply(p["fingerprint"], approved=True)

    def test_ha_check_failure_leaves_all_original(self):
        p = self.engine.plan()
        self.api.valid = False
        with self.assertRaises(SyncError):
            self.engine.apply(p["fingerprint"], approved=True)
        for name, raw in self.initial.items():
            self.assertEqual(self.home.joinpath("dashboards/dh/views", name).read_bytes(), raw)

    def test_post_install_ha_validation_failure_restores_files(self):
        p = self.engine.plan()
        old = self.api.check_config
        counter = [0]
        def check():
            counter[0] += 1
            return counter[0] < 2
        self.api.check_config = check
        with self.assertRaises(SyncError):
            self.engine.apply(p["fingerprint"], approved=True)
        for name, raw in self.initial.items():
            self.assertEqual(self.home.joinpath("dashboards/dh/views", name).read_bytes(), raw)
        self.assertEqual(self.engine.last_transaction()["phase"], "recovery_required")

    def test_rollback_refuses_new_user_changes(self):
        p = self.engine.plan()
        self.engine.apply(p["fingerprint"], approved=True)
        file = self.home / "dashboards/dh/views/11_pve_ups.yaml"
        file.write_text("user-customized")
        with self.assertRaisesRegex(SyncError, "modified"):
            self.engine.rollback(approved=True)
        self.assertEqual(file.read_text(), "user-customized")

    def test_storage_duplicate_blocks(self):
        file = self.home / ".storage/lovelace.dashboard_system"
        file.write_text(json.dumps({"data": {"config": {"views": [
            {"path": "dh_pve_agent", "title": "Duplicate"},
        ]}}}))
        with self.assertRaisesRegex(SyncError, "Storage view"):
            self.engine.plan()

    def test_duplicate_managed_path_blocks(self):
        self.home.joinpath("dashboards/dh/views/99_duplicate.yaml").write_text(
            "path: dh_pve_agent\ntitle: Dup\n"
        )
        with self.assertRaisesRegex(SyncError, "Duplicate Lovelace path"):
            self.engine.plan()

    def test_malformed_canonical_rejected(self):
        r = RESOURCES[0]
        self.sources[r.source] = b"path: bad\n"
        with self.assertRaisesRegex(SyncError, "metadata"):
            self.engine.plan()

    def test_existing_symlink_refused(self):
        filename = self.home.joinpath("dashboards/dh/views/10_pve_proxmox.yaml")
        real = filename.with_suffix(".backup")
        filename.rename(real)
        filename.symlink_to(real)
        with self.assertRaises(SyncError):
            self.engine.plan()

    def test_no_config_registration_blocks(self):
        self.home.joinpath("dashboards/dh/ui.yaml").unlink()
        with self.assertRaises(SyncError):
            self.engine.plan()


if __name__ == "__main__":
    unittest.main()
