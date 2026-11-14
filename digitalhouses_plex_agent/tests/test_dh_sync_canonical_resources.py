"""DH Sync canonical Plex YAML remains the operator-approved snapshot."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
VIEW = ROOT / "dashboards" / "ru" / "10_plex.yaml"
VIEW_EXAMPLE = ROOT / "examples" / "lovelace" / "plex-dashboard.yaml"
PACKAGE = ROOT / "packages" / "common" / "dh_plex_app_package.yaml"
PACKAGE_EXAMPLE = ROOT / "examples" / "packages" / "dh_plex_app_package.yaml"

VIEW_HEADER = (
    "# DH-View: dh_plex_agent\n"
    "# DH-View-Version: 1.0.0\n"
    "# DH-View-Date: 2026-11-14\n"
    "# DH-Compatible-Agent: >=0.8.17,<0.8.18\n"
)
PACKAGE_HEADER = (
    "# DH-Package: dh_app_plex_monitoring_package\n"
    "# DH-Package-Version: 1.0.0\n"
    "# DH-Package-Date: 2026-11-14\n"
    "# DH-Compatible-Agent: >=0.8.17,<0.8.18\n"
)


class DhSyncCanonicalPlexResourcesTests(unittest.TestCase):
    def test_view_is_exact_approved_snapshot_plus_comments(self):
        canonical = VIEW.read_text(encoding="utf-8")
        source = VIEW_EXAMPLE.read_text(encoding="utf-8")
        self.assertTrue(canonical.startswith(VIEW_HEADER + "\n"))
        self.assertEqual(canonical[len(VIEW_HEADER) + 1 :], source)
        self.assertTrue(source.startswith("type: sections\n"))
        self.assertIn("\npath: dh-plex-agent\n", source)
        self.assertIn("\ntitle: Plex\n", source)
        self.assertNotIn("\nlovelace:", source)
        self.assertIn("# DH-Compatible-Agent: >=0.8.17,<0.8.18", canonical)

    def test_package_is_exact_deployed_snapshot_plus_comments(self):
        canonical = PACKAGE.read_text(encoding="utf-8")
        source = PACKAGE_EXAMPLE.read_text(encoding="utf-8")
        self.assertTrue(canonical.startswith(PACKAGE_HEADER + "\n"))
        self.assertEqual(canonical[len(PACKAGE_HEADER) + 1 :], source)
        self.assertIn("\ndh_app_plex_monitoring_package:\n", source)
        self.assertIn("# DH-Compatible-Agent: >=0.8.17,<0.8.18", canonical)

        included, excluded = source.split("    exclude:\n", 1)
        find_ids = lambda text: re.findall(
            r"^\s*- ((?:sensor|binary_sensor|event)\.dh_plex_agent_[a-z0-9_]+)$",
            text, re.M,
        )
        included_ids = find_ids(included)
        excluded_ids = find_ids(excluded)
        self.assertEqual(len(included_ids), 24)
        self.assertEqual(len(excluded_ids), 6)
        self.assertEqual(len(set(included_ids)), len(included_ids))
        self.assertEqual(len(set(excluded_ids)), len(excluded_ids))
        self.assertFalse(set(included_ids).intersection(excluded_ids))
        self.assertIn("binary_sensor.dh_plex_agent_video_transcoding_active", included_ids)
        self.assertIn("binary_sensor.dh_plex_agent_audio_transcoding_active", included_ids)
        self.assertIn("event.dh_plex_agent_gpu_diagnostic", excluded_ids)

    def test_compatibility_is_limited_to_home_verified_agent_release(self):
        # Dashboard/package compatibility is *independent* of the agent's
        # executable release. Do not expand it on a VERSION bump alone.
        for path in (VIEW, PACKAGE):
            metadata = path.read_text().splitlines()[:5]
            self.assertEqual(
                [x for x in metadata if x.startswith("# DH-Compatible-Agent: ")],
                ["# DH-Compatible-Agent: >=0.8.17,<0.8.18"],
            )
            self.assertNotIn("# DH-Compatible-App:", "\n".join(metadata))

    def test_no_sidebar_registration_or_home_specific_ip(self):
        view = VIEW.read_text()
        package = PACKAGE.read_text()
        for text in (view, package):
            self.assertNotIn("\nlovelace:", text)
            self.assertNotIn("192.168.11.", text)
        self.assertNotIn("\nviews:", view)

    def test_non_destructive_single_locale_pilot(self):
        self.assertFalse((ROOT / "dashboards" / "en" / "10_plex.yaml").exists())
        self.assertFalse((ROOT / "packages" / "common" / "dh_plex_agent_recorder_package.yaml").exists())
        self.assertTrue((ROOT / "docs" / "DH_SYNC_COMPATIBILITY.md").is_file())


if __name__ == "__main__":
    unittest.main()
