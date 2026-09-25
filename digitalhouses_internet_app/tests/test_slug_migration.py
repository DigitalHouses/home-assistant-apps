from __future__ import annotations

import io
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "rootfs" / "app"
sys.path.insert(0, str(APP_DIR))

from slug_migration import (
    IMPORT_COMPLETE,
    IMPORT_NONE,
    IMPORT_RESTART_REQUIRED,
    PRODUCT_ID,
    SOURCE_SLUG,
    TARGET_SLUG,
    SlugMigrationError,
    export_bridge_bundle,
    import_canonical_bundle,
)


class SlugMigrationTests(unittest.TestCase):
    def _write_json(self, root: Path, relative: str, payload) -> None:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _source_state(self, root: Path) -> dict[str, dict]:
        payloads = {
            "options.json": {
                "router_ip": "192.168.11.1",
                "telemetry_enabled": True,
                "log_level": "info",
            },
            "telemetry.json": {
                "schema_version": 1,
                "installation_id": "5d6a6bc5-62c9-4d37-a90a-1bb86b79cda8",
                "installation_token": "ab" * 32,
                "last_success_epoch": 1234,
            },
            "runtime/outages.json": {
                "month": "2026-09",
                "outages": [{"from": "2026-09-25T01:00:00+05:00"}],
            },
            "runtime/traffic.json": {
                "schema_version": 1,
                "total": {"download_bytes": 123, "upload_bytes": 456},
            },
            "runtime/recovery.json": {
                "schema_version": 1,
                "stopped": True,
                "cycle": 2,
            },
        }
        for relative, payload in payloads.items():
            self._write_json(root, relative, payload)
        return payloads

    def _export(self, old_data: Path, bundle: Path) -> dict[str, dict]:
        source = self._source_state(old_data)
        export_bridge_bundle(
            app_version="0.1.12",
            data_dir=old_data,
            bundle_file=bundle,
            settings_reader=lambda: {
                "boot": "auto",
                "auto_update": False,
                "watchdog": False,
            },
        )
        return source

    def test_bridge_export_contains_only_explicit_state_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = root / "old"
            bundle = root / "share" / "bundle.tar.gz"
            payloads = self._source_state(data)
            self._write_json(data, "runtime/not_contract_state.json", {"x": 1})

            result = export_bridge_bundle(
                app_version="0.1.12",
                data_dir=data,
                bundle_file=bundle,
                settings_reader=lambda: {},
            )

            self.assertEqual(result["files"], len(payloads))
            with tarfile.open(bundle, "r:gz") as archive:
                names = set(archive.getnames())
                self.assertIn("manifest.json", names)
                self.assertIn("data/options.json", names)
                self.assertIn("data/telemetry.json", names)
                self.assertNotIn("data/runtime/not_contract_state.json", names)
                manifest = json.load(archive.extractfile("manifest.json"))
                self.assertEqual(manifest["product"], PRODUCT_ID)
                self.assertEqual(manifest["source_slug"], SOURCE_SLUG)
                self.assertEqual(manifest["target_slug"], TARGET_SLUG)
                self.assertEqual(manifest["source_version"], "0.1.12")

    def test_options_change_requires_restart_then_import_completes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old_data = root / "old"
            new_data = root / "new"
            bundle = root / "share" / "bundle.tar.gz"
            source = self._export(old_data, bundle)
            self._write_json(
                new_data,
                "options.json",
                {"router_ip": "192.168.1.1", "telemetry_enabled": False},
            )

            applied: list[dict] = []
            status = import_canonical_bundle(
                data_dir=new_data,
                bundle_file=bundle,
                settings_applier=lambda settings: applied.append(settings),
            )

            self.assertEqual(status, IMPORT_RESTART_REQUIRED)
            self.assertEqual(len(applied), 1)
            self.assertEqual(applied[0]["options"], source["options.json"])
            self.assertTrue(
                (new_data / ".slug_migration_v1_options_pending.json").is_file()
            )
            self.assertFalse((new_data / "telemetry.json").exists())

            # Supervisor exposes persisted options to the App only when the
            # canonical container is started again.
            self._write_json(new_data, "options.json", source["options.json"])

            status = import_canonical_bundle(
                data_dir=new_data,
                bundle_file=bundle,
                settings_applier=lambda _settings: self.fail(
                    "settings must not be applied twice"
                ),
            )
            self.assertEqual(status, IMPORT_COMPLETE)
            self.assertFalse(
                (new_data / ".slug_migration_v1_options_pending.json").exists()
            )
            self.assertEqual(
                json.loads((new_data / "telemetry.json").read_text()),
                source["telemetry.json"],
            )
            self.assertEqual(
                json.loads((new_data / "runtime/outages.json").read_text()),
                source["runtime/outages.json"],
            )

    def test_013_side_effect_recovers_when_options_are_already_active(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old_data = root / "old"
            new_data = root / "new"
            bundle = root / "share" / "bundle.tar.gz"
            source = self._export(old_data, bundle)

            # 0.1.13 successfully POSTed legacy options to Supervisor before it
            # failed while waiting for the running container to hot-update.
            self._write_json(new_data, "options.json", source["options.json"])

            status = import_canonical_bundle(
                data_dir=new_data,
                bundle_file=bundle,
                settings_applier=lambda _settings: self.fail(
                    "already-active options must not be posted again"
                ),
            )

            self.assertEqual(status, IMPORT_COMPLETE)
            telemetry = json.loads((new_data / "telemetry.json").read_text())
            self.assertEqual(
                telemetry["installation_id"],
                source["telemetry.json"]["installation_id"],
            )

    def test_completed_import_ignores_refreshed_legacy_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old_data = root / "old"
            new_data = root / "new"
            bundle = root / "share" / "bundle.tar.gz"
            source = self._export(old_data, bundle)
            self._write_json(new_data, "options.json", source["options.json"])

            self.assertEqual(
                import_canonical_bundle(
                    data_dir=new_data,
                    bundle_file=bundle,
                    settings_applier=lambda _settings: self.fail(
                        "options already match"
                    ),
                ),
                IMPORT_COMPLETE,
            )

            newer = {"newer": True}
            self._write_json(new_data, "runtime/outages.json", newer)

            # A rollback start of the legacy bridge App refreshes the shared
            # bundle and therefore changes its hash. Completed canonical state
            # must remain authoritative and must not be re-imported.
            self._write_json(
                old_data,
                "runtime/outages.json",
                {"legacy_refresh": True},
            )
            export_bridge_bundle(
                app_version="0.1.12",
                data_dir=old_data,
                bundle_file=bundle,
                settings_reader=lambda: {},
            )

            self.assertEqual(
                import_canonical_bundle(
                    data_dir=new_data,
                    bundle_file=bundle,
                    settings_applier=lambda _settings: self.fail(
                        "completed migration must ignore refreshed bridge bundle"
                    ),
                ),
                IMPORT_NONE,
            )
            self.assertEqual(
                json.loads((new_data / "runtime/outages.json").read_text()),
                newer,
            )

    def test_pending_import_rejects_restart_without_expected_options(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old_data = root / "old"
            new_data = root / "new"
            bundle = root / "share" / "bundle.tar.gz"
            self._export(old_data, bundle)
            self._write_json(new_data, "options.json", {"router_ip": "wrong"})

            self.assertEqual(
                import_canonical_bundle(
                    data_dir=new_data,
                    bundle_file=bundle,
                    settings_applier=lambda _settings: None,
                ),
                IMPORT_RESTART_REQUIRED,
            )

            with self.assertRaises(SlugMigrationError):
                import_canonical_bundle(
                    data_dir=new_data,
                    bundle_file=bundle,
                    settings_applier=lambda _settings: self.fail(
                        "pending migration must not repost options"
                    ),
                )

    def test_tampered_bundle_is_rejected_before_settings_are_applied(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old_data = root / "old"
            new_data = root / "new"
            bundle = root / "share" / "bundle.tar.gz"
            self._export(old_data, bundle)

            tampered = root / "share" / "tampered.tar.gz"
            with tarfile.open(bundle, "r:gz") as source_archive:
                manifest = source_archive.extractfile("manifest.json").read()
                options = source_archive.extractfile("data/options.json").read()
            with tarfile.open(tampered, "w:gz") as archive:
                for name, payload in (
                    ("manifest.json", manifest),
                    ("data/options.json", options),
                    ("data/telemetry.json", b'{"tampered":true}\n'),
                ):
                    info = tarfile.TarInfo(name)
                    info.size = len(payload)
                    archive.addfile(info, io.BytesIO(payload))

            with self.assertRaises(SlugMigrationError):
                import_canonical_bundle(
                    data_dir=new_data,
                    bundle_file=tampered,
                    settings_applier=lambda _settings: self.fail(
                        "tampered bundle must not apply settings"
                    ),
                )


if __name__ == "__main__":
    unittest.main()
