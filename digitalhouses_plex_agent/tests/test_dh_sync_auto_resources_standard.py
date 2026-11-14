"""DH Sync 0.4.0 publishable Plex resources: source contract, not HA writes.

The running Sync App admits any DigitalHouses repository and reads only the
three canonical product directories. These product tests guard its input.
"""
from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlsplit

from app.build_info import load_build_info
from app.config import load_config
from app.discovery import build_sync_payload, build_topics


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = ROOT.parent
VIEW = ROOT / "dashboards/ru/10_plex.yaml"
PACKAGE = ROOT / "packages/common/dh_plex_app_package.yaml"
CATEGORIES = ("dashboards/ru", "packages/common", "packages/locales/ru")


def _published_files() -> list[Path]:
    return [
        f.relative_to(ROOT)
        for category in CATEGORIES
        for f in (ROOT / category).glob("*.yaml")
        if f.is_file()
    ]


def _key_at_start(text: str, key: str) -> str:
    match = re.findall(
        rf"(?m)^{re.escape(key)}: (\S+)\s*$",
        text,
    )
    if len(match) != 1:
        raise AssertionError(f"Expected exactly one {key} at the root")
    return match[0]


class AutoResourceStandardTests(unittest.TestCase):
    def test_only_real_published_canonical_files(self):
        published = set(_published_files())
        self.assertEqual(
            published,
            {
                Path("dashboards/ru/10_plex.yaml"),
                Path("packages/common/dh_plex_app_package.yaml"),
            },
        )
        self.assertTrue((ROOT / "examples/lovelace/plex-dashboard.yaml").is_file())
        self.assertTrue((ROOT / "examples/packages/dh_plex_app_package.yaml").is_file())
        self.assertFalse(any("examples" in f.parts for f in published))
        # No dummy locale files or unapproved notification delivery rules.
        self.assertFalse((ROOT / "packages/locales/ru").is_dir())

    def test_one_standalone_view_with_stable_path(self):
        views = (ROOT / "dashboards/ru").glob("*.yaml")
        paths = []
        for view in views:
            yaml = view.read_text(encoding="utf-8")
            paths.append(_key_at_start(yaml, "path"))
            self.assertEqual(_key_at_start(yaml, "type"), "sections")
            self.assertIn("title: Plex", yaml)
            self.assertNotRegex(yaml, r"(?m)^lovelace:")
            self.assertNotRegex(yaml, r"(?m)^views:")
            self.assertNotIn("!include_dir_list", yaml)
            self.assertNotIn("# DH-Compatible-Agent:", yaml)
        self.assertEqual(paths, ["dh-plex-agent"])
        self.assertEqual(len(paths), len(set(paths)))

    def test_one_recorder_package_key_and_no_secrets(self):
        packages = list((ROOT / "packages/common").glob("*.yaml"))
        keys = []
        for package in packages:
            yaml = package.read_text(encoding="utf-8")
            top_level = re.findall(r"(?m)^([a-zA-Z_][a-zA-Z0-9_]*):\s*$", yaml)
            self.assertEqual(len(top_level), 1)
            keys.extend(top_level)
            self.assertNotIn("!include_dir_merge_named", yaml)
            self.assertNotIn("# DH-Compatible-Agent:", yaml)
            self.assertNotRegex(yaml, r"(?im)^\s*(?:host|password|token):")
            self.assertNotIn("notify.mobile_app_", yaml)
            self.assertNotIn("script.write2admins", yaml)
        self.assertEqual(keys, ["dh_app_plex_monitoring_package"])
        self.assertEqual(len(keys), len(set(keys)))

    def test_mqtt_source_claim_resolves_existing_product_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = Path(directory) / "plex.ini"
            cfg.write_text("[mqtt]\nhost=broker\n", encoding="utf-8")
            config = load_config(cfg)
            self.assertEqual(build_topics(config).sync,
                "DigitalHouses/Global/digitalhouses_plex_agent/sync")
        claim = build_sync_payload(load_build_info(ROOT))
        registry = json.loads((REPOSITORY_ROOT /
            "digitalhouses-stats/digitalhouses_stats/product_registry.json").read_text())
        record = next(x for x in registry["products"] if x["id"] == claim["product_id"])
        self.assertEqual(record["repository_directory"], claim["product_path"])
        self.assertEqual(claim["type"], "agent")
        self.assertEqual(claim["schema"], 1)
        self.assertEqual(claim["version"], (ROOT / "VERSION").read_text().strip())
        self.assertEqual(
            set(claim),
            {"schema", "product_id", "type", "version", "repository", "product_path"},
        )
        url = urlsplit(claim["repository"])
        self.assertEqual(url.scheme, "https")
        self.assertEqual(url.netloc, "github.com")
        self.assertEqual(url.path.split("/")[1].casefold(), "digitalhouses")
        self.assertEqual(url.path.split("/")[2], "home-assistant-apps")
        self.assertTrue(all(
            (REPOSITORY_ROOT / claim["product_path"] / category).exists()
            for category in ("dashboards/ru", "packages/common")
        ))

    def test_no_executable_or_resource_release_coupling(self):
        # Changes to the files above may ship independently from the installed
        # agent release. Informational view/package revisions do not gate sync.
        self.assertIn("# DH-View-Version: 1.0.0", VIEW.read_text())
        self.assertIn("# DH-Package-Version: 1.0.0", PACKAGE.read_text())
        self.assertEqual(load_build_info(ROOT).version, (ROOT / "VERSION").read_text().strip())
        self.assertNotIn("# DH-Compatible-", VIEW.read_text())
        self.assertNotIn("# DH-Compatible-", PACKAGE.read_text())


if __name__ == "__main__":
    unittest.main()
