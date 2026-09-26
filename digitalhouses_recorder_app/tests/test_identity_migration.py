from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

APP_DIR = (
    Path(__file__).resolve().parents[1]
    / "rootfs"
    / "app"
)
sys.path.insert(0, str(APP_DIR))

from identity_migration import (
    CANONICAL_BASE_TOPIC,
    CANONICAL_DEVICE_ID,
    LEGACY_BASE_TOPIC,
    LEGACY_DEVICE_ID,
    PHASE_BRIDGE,
    PHASE_COMPLETED,
    ensure_bridge_state,
    mark_cleanup_complete,
)


class IdentityMigrationStateTests(unittest.TestCase):
    def test_first_bridge_start_persists_migration_state(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "identity.json"
            self.assertTrue(
                ensure_bridge_state(
                    "0.1.15",
                    path=path,
                )
            )
            state = json.loads(
                path.read_text(encoding="utf-8")
            )
            self.assertEqual(
                state["phase"],
                PHASE_BRIDGE,
            )
            self.assertTrue(
                state["cleanup_pending"]
            )
            self.assertEqual(
                state["legacy_base_topic"],
                LEGACY_BASE_TOPIC,
            )
            self.assertEqual(
                state["legacy_device_id"],
                LEGACY_DEVICE_ID,
            )
            self.assertEqual(
                state["canonical_base_topic"],
                CANONICAL_BASE_TOPIC,
            )
            self.assertEqual(
                state["canonical_device_id"],
                CANONICAL_DEVICE_ID,
            )

    def test_bridge_start_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "identity.json"
            self.assertTrue(
                ensure_bridge_state(
                    "0.1.15",
                    path=path,
                )
            )
            first = json.loads(
                path.read_text(encoding="utf-8")
            )
            self.assertTrue(
                ensure_bridge_state(
                    "0.1.15",
                    path=path,
                )
            )
            second = json.loads(
                path.read_text(encoding="utf-8")
            )
            self.assertEqual(first, second)

    def test_completed_cleanup_never_reenables_legacy_on_rollback(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "identity.json"
            ensure_bridge_state(
                "0.1.15",
                path=path,
            )
            mark_cleanup_complete(
                "0.1.16",
                path=path,
            )
            state = json.loads(
                path.read_text(encoding="utf-8")
            )
            self.assertEqual(
                state["phase"],
                PHASE_COMPLETED,
            )
            self.assertFalse(
                state["cleanup_pending"]
            )

            self.assertFalse(
                ensure_bridge_state(
                    "0.1.15",
                    path=path,
                )
            )
            after_rollback = json.loads(
                path.read_text(encoding="utf-8")
            )
            self.assertEqual(
                after_rollback["phase"],
                PHASE_COMPLETED,
            )
            self.assertEqual(
                after_rollback["release_version"],
                "0.1.16",
            )


if __name__ == "__main__":
    unittest.main()
