from __future__ import annotations

import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "rootfs" / "app"
sys.path.insert(0, str(APP_DIR))

from slug_migration import (
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
                settings_reader=lambda: {
                    "boot": "auto",
                    "auto_update": False,
                    "watchdog": True,
                },
            )

            self.assertEqual(result["files"], len(payloads))
            self.assertTrue(bundle.is_file())
            with tarfile.open(bundle, "r:gz") as archive:
                names = set(archive.getnames())
                self.assertIn("manifest.json", names)
                self.assertIn("data/options.json", names)
                self.assertIn("data/telemetry.json", names)
                self.assertNotIn(
                    "data/runtime/not_contract_state.json",
                    names,
                )
                manifest = json.load(archive.extractfile("manifest.json"))
                self.assertEqual(manifest["product"], PRODUCT_ID)
                self.assertEqual(manifest["source_slug"], SOURCE_SLUG)
                self.assertEqual(manifest["target_slug"], TARGET_SLUG)
                self.assertEqual(manifest["source_version"], "0.1.12")

    def test_import_preserves_options_telemetry_identity_and_runtime_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old_data = root / "old"
            new_data = root / "new"
            bundle = root / "share" / "bundle.tar.gz"
            source = self._source_state(old_data)

            export_bridge_bundle(
                app_version="0.1.12",
                data_dir=old_data,
                bundle_file=bundle,
                settings_reader=lambda: {
                    "boot": "auto",
                    "auto_update": True,
                    "watchdog": False,
                },
            )

            applied: list[dict] = []

            def apply(settings: dict) -> None:
                applied.append(settings)
                self._write_json(
                    new_data,
                    "options.json",
                    settings["options"],
                )

            self.assertTrue(
                import_canonical_bundle(
                    data_dir=new_data,
                    bundle_file=bundle,
                    settings_applier=apply,
                )
            )
            self.assertEqual(len(applied), 1)
            self.assertEqual(
                applied[0]["options"],
                source["options.json"],
            )
            self.assertTrue(applied[0]["auto_update"])
            self.assertFalse(applied[0]["watchdog"])

            for relative in (
                "telemetry.json",
                "runtime/outages.json",
                "runtime/traffic.json",
                "runtime/recovery.json",
            ):
                self.assertEqual(
                    json.loads((new_data / relative).read_text()),
                    source[relative],
                )

            self.assertEqual(
                json.loads((new_data / "telemetry.json").read_text())[
                    "installation_id"
                ],
                source["telemetry.json"]["installation_id"],
            )

    def test_import_is_idempotent_and_does_not_overwrite_newer_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old_data = root / "old"
            new_data = root / "new"
            bundle = root / "share" / "bundle.tar.gz"
            self._source_state(old_data)
            export_bridge_bundle(
                app_version="0.1.12",
                data_dir=old_data,
                bundle_file=bundle,
                settings_reader=lambda: {},
            )

            def apply(settings: dict) -> None:
                self._write_json(
                    new_data,
                    "options.json",
                    settings["options"],
                )

            self.assertTrue(
                import_canonical_bundle(
                    data_dir=new_data,
                    bundle_file=bundle,
                    settings_applier=apply,
                )
            )
            newer = {"newer": True}
            self._write_json(new_data, "runtime/outages.json", newer)

            self.assertFalse(
                import_canonical_bundle(
                    data_dir=new_data,
                    bundle_file=bundle,
                    settings_applier=lambda _settings: self.fail(
                        "settings must not be applied twice"
                    ),
                )
            )
            self.assertEqual(
                json.loads((new_data / "runtime/outages.json").read_text()),
                newer,
            )

    def test_tampered_bundle_is_rejected_before_settings_are_applied(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old_data = root / "old"
            new_data = root / "new"
            bundle = root / "share" / "bundle.tar.gz"
            self._source_state(old_data)
            export_bridge_bundle(
                app_version="0.1.12",
                data_dir=old_data,
                bundle_file=bundle,
                settings_reader=lambda: {},
            )

            # Rebuild the archive with a modified telemetry payload while
            # retaining the original manifest hash.
            tampered = root / "share" / "tampered.tar.gz"
            with tarfile.open(bundle, "r:gz") as source_archive:
                manifest = source_archive.extractfile("manifest.json").read()
                options = source_archive.extractfile("data/options.json").read()
            with tarfile.open(tampered, "w:gz") as archive:
                import io

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
