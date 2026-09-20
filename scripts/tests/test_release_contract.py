import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from release_contract import ReleaseContractError, release_metadata


class ReleaseContractTests(unittest.TestCase):
    def _write(self, root: Path, path: str, content: str) -> None:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def test_linux_agent_future_release_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._write(root, "dh_pve_app/VERSION", "0.6.0\n")
            self._write(
                root,
                "dh_pve_app/CHANGELOG.md",
                "# Changelog\n\n## Unreleased\n\n## 0.6.0\n\n- New release.\n\n## 0.5.6\n\n- Old.\n",
            )

            metadata = release_metadata(
                root,
                product="digitalhouses_pve_agent",
                version="0.6.0",
            )

            self.assertEqual(metadata.tag, "digitalhouses_pve_agent-v0.6.0")
            self.assertEqual(metadata.title, "DigitalHouses PVE Agent v0.6.0")
            self.assertEqual(metadata.notes, "- New release.")
            self.assertFalse(metadata.prerelease)

    def test_haos_app_reads_config_version(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._write(
                root,
                "digitalhouses_db_monitoring/config.yaml",
                "name: DigitalHouses DB Monitoring\nversion: 0.2.0\n",
            )
            self._write(
                root,
                "digitalhouses_db_monitoring/CHANGELOG.md",
                "# Changelog\n\n## 0.2.0\n\n- Recorder release.\n",
            )

            metadata = release_metadata(
                root,
                product="digitalhouses_recorder_app",
                version="0.2.0",
            )

            self.assertEqual(metadata.tag, "digitalhouses_recorder_app-v0.2.0")
            self.assertEqual(metadata.notes, "- Recorder release.")

    def test_rejects_version_at_or_before_policy_baseline(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._write(root, "digitalhouses_plex_monitoring/VERSION", "0.2.2\n")
            self._write(
                root,
                "digitalhouses_plex_monitoring/CHANGELOG.md",
                "# Changelog\n\n## 0.2.2\n\n- Existing release.\n",
            )

            with self.assertRaisesRegex(ReleaseContractError, "policy baseline"):
                release_metadata(
                    root,
                    product="digitalhouses_plex_agent",
                    version="0.2.2",
                )

    def test_rejects_source_version_mismatch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._write(root, "digitalhouses_plex_monitoring/VERSION", "0.3.0\n")
            self._write(
                root,
                "digitalhouses_plex_monitoring/CHANGELOG.md",
                "# Changelog\n\n## 0.3.0\n\n- Plex release.\n",
            )

            with self.assertRaisesRegex(ReleaseContractError, "source version"):
                release_metadata(
                    root,
                    product="digitalhouses_plex_agent",
                    version="0.3.1",
                )

    def test_rejects_nonempty_unreleased_section(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._write(root, "dh_pve_app/VERSION", "0.6.0\n")
            self._write(
                root,
                "dh_pve_app/CHANGELOG.md",
                "# Changelog\n\n## Unreleased\n\n- Not moved yet.\n\n## 0.6.0\n\n- Release.\n",
            )

            with self.assertRaisesRegex(ReleaseContractError, "Unreleased"):
                release_metadata(
                    root,
                    product="digitalhouses_pve_agent",
                    version="0.6.0",
                )

    def test_prerelease_version_sets_prerelease_flag(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._write(root, "dh_pve_app/VERSION", "0.6.0-rc.1\n")
            self._write(
                root,
                "dh_pve_app/CHANGELOG.md",
                "# Changelog\n\n## 0.6.0-rc.1\n\n- Candidate.\n",
            )

            metadata = release_metadata(
                root,
                product="digitalhouses_pve_agent",
                version="0.6.0-rc.1",
            )

            self.assertTrue(metadata.prerelease)


if __name__ == "__main__":
    unittest.main()
