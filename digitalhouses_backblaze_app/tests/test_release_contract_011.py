import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = ROOT / "rootfs/app/app.py"
DISCOVERY_SOURCE = ROOT / "rootfs/app/discovery.py"
RUN_SCRIPT = ROOT / "rootfs/run.sh"
CHANGELOG = ROOT / "CHANGELOG.md"
README = ROOT / "README.md"


class ReleaseContract011Tests(unittest.TestCase):
    def test_release_version_has_no_synthetic_runtime_fallback(self):
        app = APP_SOURCE.read_text(encoding="utf-8")
        run = RUN_SCRIPT.read_text(encoding="utf-8")

        self.assertIn('APP_VERSION = os.environ.get("APP_VERSION")', app)
        self.assertIn(
            'raise RuntimeError("APP_VERSION must be a valid semantic version")',
            app,
        )
        self.assertNotIn("-local", app)
        self.assertNotIn("APP_VERSION:-unknown", run)
        self.assertIn("APP_VERSION is required.", run)

    def test_discovery_manifest_is_persistent_and_transactional(self):
        app = APP_SOURCE.read_text(encoding="utf-8")
        discovery = DISCOVERY_SOURCE.read_text(encoding="utf-8")

        self.assertIn(
            'DISCOVERY_MANIFEST_PATH = Path("/data/discovery_manifest.json")',
            discovery,
        )
        sync = app.split("    def sync_discovery(self) -> bool:", 1)[1].split(
            "    def refresh(self) -> bool:",
            1,
        )[0]
        self.assertIn("removed_discovery_components(", sync)
        self.assertIn("discovery_cleanup_payload(", sync)
        self.assertIn("confirm=True", sync)
        self.assertIn("save_discovery_manifest(current_manifest)", sync)
        self.assertLess(
            sync.index("discovery_cleanup_payload("),
            sync.index("save_discovery_manifest(current_manifest)"),
        )

    def test_011_release_is_documented(self):
        changelog = CHANGELOG.read_text(encoding="utf-8")
        readme = README.read_text(encoding="utf-8")

        self.assertIn("## 0.1.11", changelog)
        self.assertIn(
            "Version 0.1.11 is the current stable production release.",
            readme,
        )


if __name__ == "__main__":
    unittest.main()
