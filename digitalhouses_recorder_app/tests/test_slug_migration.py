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
    IMPORT_RESTART_REQUIRED,
    PRODUCT_ID,
    SOURCE_SLUG,
    TARGET_SLUG,
    SlugMigrationError,
    export_bridge_bundle,
    import_canonical_bundle,
)


class SlugMigrationTests(unittest.TestCase):
    def _write_options(self, root: Path, payload: dict | None = None) -> dict:
        options = payload or {
            "database_type": "postgresql",
            "postgresql": {
                "host": "192.168.11.40",
                "port": 5432,
                "database": "homeassistant",
                "username": "homeassistant",
                "password": "secret",
            },
            "storage": {
                "source": "automatic",
                "ssh_host": "",
                "ssh_port": 22,
                "ssh_username": "",
                "ssh_password": "",
                "path": "",
            },
            "publish_interval_minutes": 1,
            "recorder_stale_seconds": 300,
            "timezone": "Asia/Almaty",
            "log_level": "info",
        }
        root.mkdir(parents=True, exist_ok=True)
        (root / "options.json").write_text(
            json.dumps(options, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return options

    def _export(self, data: Path, bundle: Path) -> None:
        export_bridge_bundle(
            app_version="0.1.9",
            data_dir=data,
            bundle_file=bundle,
            settings_reader=lambda: {
                "boot": "auto",
                "auto_update": False,
                "watchdog": False,
            },
        )

    def test_bridge_export_contains_only_recorder_persistent_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = root / "old"
            bundle = root / "share" / "bundle.tar.gz"
            self._write_options(data)
            (data / "ssh_known_hosts").write_text(
                "192.168.11.40 ssh-ed25519 AAAATEST\n",
                encoding="utf-8",
            )
            (data / "not_contract_state.json").write_text(
                '{"must_not_move":true}\n',
                encoding="utf-8",
            )

            result = export_bridge_bundle(
                app_version="0.1.9",
                data_dir=data,
                bundle_file=bundle,
                settings_reader=lambda: {
                    "boot": "auto",
                    "auto_update": False,
                    "watchdog": True,
                },
            )

            self.assertEqual(result["files"], 2)
            with tarfile.open(bundle, "r:gz") as archive:
                names = set(archive.getnames())
                self.assertEqual(
                    names,
                    {
                        "manifest.json",
                        "data/options.json",
                        "data/ssh_known_hosts",
                    },
                )
                manifest_file = archive.extractfile("manifest.json")
                self.assertIsNotNone(manifest_file)
                manifest = json.load(manifest_file)
                self.assertEqual(manifest["product"], PRODUCT_ID)
                self.assertEqual(manifest["source_slug"], SOURCE_SLUG)
                self.assertEqual(manifest["target_slug"], TARGET_SLUG)
                self.assertEqual(manifest["source_version"], "0.1.9")
                self.assertEqual(manifest["supervisor_settings"]["boot"], "auto")
                self.assertIn("sha256", manifest["files"]["options.json"])
                self.assertIn("sha256", manifest["files"]["ssh_known_hosts"])

    def test_options_json_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = root / "old"
            data.mkdir(parents=True)
            (data / "ssh_known_hosts").write_text("host key\n", encoding="utf-8")

            with self.assertRaisesRegex(
                SlugMigrationError,
                "required /data/options.json is missing",
            ):
                export_bridge_bundle(
                    app_version="0.1.9",
                    data_dir=data,
                    bundle_file=root / "bundle.tar.gz",
                    settings_reader=lambda: {},
                )

    def test_ssh_known_hosts_is_optional(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = root / "old"
            bundle = root / "bundle.tar.gz"
            self._write_options(data)

            result = export_bridge_bundle(
                app_version="0.1.9",
                data_dir=data,
                bundle_file=bundle,
                settings_reader=lambda: {},
            )

            self.assertEqual(result["files"], 1)
            with tarfile.open(bundle, "r:gz") as archive:
                self.assertEqual(
                    set(archive.getnames()),
                    {"manifest.json", "data/options.json"},
                )

    def test_supervisor_settings_failure_does_not_break_export(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = root / "old"
            bundle = root / "bundle.tar.gz"
            self._write_options(data)

            def broken_settings_reader():
                raise RuntimeError("supervisor unavailable")

            export_bridge_bundle(
                app_version="0.1.9",
                data_dir=data,
                bundle_file=bundle,
                settings_reader=broken_settings_reader,
            )

            with tarfile.open(bundle, "r:gz") as archive:
                manifest_file = archive.extractfile("manifest.json")
                self.assertIsNotNone(manifest_file)
                manifest = json.load(manifest_file)
                self.assertEqual(manifest["supervisor_settings"], {})

    def test_repeated_export_atomically_replaces_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = root / "old"
            bundle = root / "share" / "bundle.tar.gz"
            self._write_options(data)
            (data / "ssh_known_hosts").write_text("first\n", encoding="utf-8")
            self._export(data, bundle)

            (data / "ssh_known_hosts").write_text("second\n", encoding="utf-8")
            self._export(data, bundle)

            with tarfile.open(bundle, "r:gz") as archive:
                known_hosts = archive.extractfile("data/ssh_known_hosts")
                self.assertIsNotNone(known_hosts)
                self.assertEqual(known_hosts.read(), b"second\n")
            self.assertEqual(list(bundle.parent.glob(".bundle.*.tar.gz")), [])

    def test_tampered_bundle_is_rejected_before_import(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old_data = root / "old"
            new_data = root / "new"
            bundle = root / "bundle.tar.gz"
            tampered = root / "tampered.tar.gz"
            self._write_options(old_data)
            (old_data / "ssh_known_hosts").write_text("original\n", encoding="utf-8")
            self._export(old_data, bundle)

            with tarfile.open(bundle, "r:gz") as source:
                manifest = source.extractfile("manifest.json").read()
                options = source.extractfile("data/options.json").read()

            with tarfile.open(tampered, "w:gz") as archive:
                for name, payload in (
                    ("manifest.json", manifest),
                    ("data/options.json", options),
                    ("data/ssh_known_hosts", b"tampered\n"),
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

    def test_future_import_preserves_options_and_ssh_known_hosts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old_data = root / "old"
            new_data = root / "new"
            bundle = root / "bundle.tar.gz"
            source_options = self._write_options(old_data)
            (old_data / "ssh_known_hosts").write_text(
                "recorder-db ssh-ed25519 AAAATEST\n",
                encoding="utf-8",
            )
            self._export(old_data, bundle)

            new_options = {"database_type": "postgresql"}
            self._write_options(new_data, new_options)
            applied: list[dict] = []

            status = import_canonical_bundle(
                data_dir=new_data,
                bundle_file=bundle,
                settings_applier=lambda settings: applied.append(settings),
            )
            self.assertEqual(status, IMPORT_RESTART_REQUIRED)
            self.assertEqual(applied[0]["options"], source_options)
            self.assertFalse((new_data / "ssh_known_hosts").exists())

            self._write_options(new_data, source_options)
            status = import_canonical_bundle(
                data_dir=new_data,
                bundle_file=bundle,
                settings_applier=lambda _settings: self.fail(
                    "settings must not be applied twice"
                ),
            )
            self.assertEqual(status, IMPORT_COMPLETE)
            self.assertEqual(
                (new_data / "ssh_known_hosts").read_text(encoding="utf-8"),
                "recorder-db ssh-ed25519 AAAATEST\n",
            )


if __name__ == "__main__":
    unittest.main()
