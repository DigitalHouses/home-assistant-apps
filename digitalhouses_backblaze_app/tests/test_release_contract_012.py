import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = ROOT / "rootfs/app/app.py"
B2_SOURCE = ROOT / "rootfs/app/backblaze.py"
DISCOVERY_SOURCE = ROOT / "rootfs/app/discovery.py"
OPERATION_SOURCE = ROOT / "rootfs/app/operation_status.py"
RUNTIME_STATE_SOURCE = ROOT / "rootfs/app/runtime_state.py"
DASHBOARD = ROOT / "examples/lovelace/dh_app_backblaze_dashboard.yaml"
CHANGELOG = ROOT / "CHANGELOG.md"
README = ROOT / "README.md"
CONFIG = ROOT / "config.yaml"
DOCKERFILE = ROOT / "Dockerfile"


class ReleaseContract012Tests(unittest.TestCase):
    def test_012_release_is_documented(self):
        self.assertIn("## 0.1.12", CHANGELOG.read_text(encoding="utf-8"))
        self.assertIn("DigitalHouses Backblaze App", README.read_text(encoding="utf-8"))

    def test_storage_tree_is_one_entity_built_from_existing_scan(self):
        b2 = B2_SOURCE.read_text(encoding="utf-8")
        discovery = DISCOVERY_SOURCE.read_text(encoding="utf-8")
        app = APP_SOURCE.read_text(encoding="utf-8")

        self.assertIn("class FolderUsage:", b2)
        self.assertIn("folder_totals", b2)
        self.assertIn('"uploadTimestamp"', b2)
        self.assertIn(
            '"sensor.dh_backblaze_storage_tree"',
            discovery,
        )
        self.assertIn("json_attributes_topic=STORAGE_TREE_TOPIC", discovery)
        self.assertIn("def build_storage_tree(", app)
        self.assertIn("self.publish_storage_tree()", app)
        self.assertNotIn("folder_state_topic", discovery)

    def test_manual_refresh_uses_canonical_operation_state(self):
        app = APP_SOURCE.read_text(encoding="utf-8")
        operation = OPERATION_SOURCE.read_text(encoding="utf-8")
        runtime_state = RUNTIME_STATE_SOURCE.read_text(encoding="utf-8")

        self.assertIn(
            'VALID_OPERATION_STATES = frozenset({"idle", "updating", "error"})',
            operation,
        )
        self.assertIn("def refresh(self, *, manual: bool = False) -> bool:", app)
        self.assertIn('operation_payload("updating"', app)
        self.assertIn('"idle" if success else "error"', app)
        self.assertIn("self._commit_last_refresh(completed_at)", app)
        self.assertIn("self.refresh(manual=manual_refresh)", app)
        self.assertIn(
            'RUNTIME_STATE_PATH = Path("/data/runtime_state.json")',
            runtime_state,
        )

    def test_dashboard_uses_tree_and_pve_style_refresh_feedback(self):
        dashboard = DASHBOARD.read_text(encoding="utf-8")
        self.assertIn("sensor.dh_backblaze_storage_tree", dashboard)
        self.assertIn("sensor.dh_backblaze_refresh_state", dashboard)
        self.assertIn("sensor.dh_backblaze_last_refresh", dashboard)
        self.assertIn("Обновление…", dashboard)
        self.assertIn(
            "background: var(--secondary-background-color)",
            dashboard,
        )


if __name__ == "__main__":
    unittest.main()
