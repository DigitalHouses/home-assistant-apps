"""Source-level DH Sync dashboard contract for Recorder App 0.1.28 and 0.1.29.

Metadata permits read-only preview; live HA frontend acceptance is required
before an operator approves installation or replacement of a dashboard.
"""
from __future__ import annotations

import hashlib
import re
import sys
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "rootfs" / "app"))

from discovery import (  # noqa: E402
    APP_AVAILABILITY_TOPIC,
    DISCOVERY_TOPIC,
    build_discovery_payload,
)
from sync_discovery import SYNC_TOPIC, build_sync_payload  # noqa: E402

CANONICAL = APP / "dashboards" / "ru" / "10_recorder.yaml"
BASELINE = APP / "examples" / "lovelace" / "dh_recorder_app_dashboard.yaml"
RELEASE_CONFIG = APP / "config.yaml"
BASELINE_GIT_BLOB_SHA1 = "45dd279a425c0165deccdb0b53e6d9fe6b37a8af"
VIEW_VERSION = "1.0.0"
VIEW_HEADER = (
    "# DH-View: dh_recorder_app\n"
    "# DH-View-Version: " + VIEW_VERSION + "\n"
    "# DH-View-Date: 2026-11-14\n"
)
HA_SERVICE_ACTIONS = {"button.press", "update.install"}
SUPERVISOR_ENTITIES = {"update.digitalhouses_recorder_app_update"}
ENTITY_REFERENCE = re.compile(
    r"\b(?:sensor|binary_sensor|button|number|event|update)\.[a-z0-9_]+\b"
)
def _git_blob_sha1(raw: bytes) -> str:
    """Git's content SHA makes the immutable 0.1.28 source baseline explicit."""
    prefix = b"blob " + str(len(raw)).encode("ascii") + b"\0"
    return hashlib.sha1(prefix + raw).hexdigest()


def _view_body(raw: str) -> str:
    lines = raw.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.strip() and not line.startswith("#"):
            return "".join(lines[i:])
    raise AssertionError("No Lovelace view body")


class RecorderDashboardCompatibilityTests(unittest.TestCase):
    def test_owner_only_metadata_and_unmodified_view_revision(self):
        view = CANONICAL.read_text(encoding="utf-8")
        self.assertTrue(view.startswith(VIEW_HEADER))
        self.assertEqual(view.count("# DH-View: "), 1)
        self.assertEqual(view.count("# DH-View-Version: "), 1)
        self.assertNotIn("# DH-Compatible-", view)
        self.assertEqual(view.splitlines()[1], "# DH-View-Version: 1.0.0")

    def test_version_metadata_does_not_create_a_source_gate(self):
        view = CANONICAL.read_text(encoding="utf-8")
        self.assertNotIn("# DH-Compatible-", view)
        self.assertIn("\nversion: 0.1.29\n", RELEASE_CONFIG.read_text(encoding="utf-8"))

    def test_exact_tagged_0128_baseline_and_original_view_body(self):
        original = BASELINE.read_bytes()
        self.assertEqual(_git_blob_sha1(original), BASELINE_GIT_BLOB_SHA1)
        canonical = CANONICAL.read_text(encoding="utf-8")
        self.assertEqual(_view_body(canonical).encode("utf-8"), original)
        self.assertTrue(original.startswith(
            b"title: DH Recorder\npath: recorder\nicon: mdi:database\n"
            b"type: sections\nmax_columns: 4\nsections:\n"
        ))
        self.assertTrue(original.endswith(b"cards: []\nbadges: []\n"))
        self.assertNotIn(b"\nlovelace:", original)
        self.assertNotIn(b"\nviews:", original)
        self.assertNotIn(b"192.168.", original)

    def test_all_recorder_entities_are_in_both_discovery_versions(self):
        body = _view_body(CANONICAL.read_text(encoding="utf-8"))
        references = set(ENTITY_REFERENCE.findall(body))
        original = build_discovery_payload("0.1.28", include_storage=True)
        current = build_discovery_payload("0.1.29", include_storage=True)
        # Only running-version metadata may differ between these releases.
        self.assertEqual(original["components"], current["components"])
        for version, payload in (("0.1.28", original), ("0.1.29", current)):
            with self.subTest(version=version):
                discovered = {
                    component["default_entity_id"]
                    for component in payload["components"].values()
                    if "default_entity_id" in component
                }
                self.assertEqual(
                    references - discovered,
                    SUPERVISOR_ENTITIES | HA_SERVICE_ACTIONS,
                )
                self.assertIn("sensor.dh_recorder_app_version", discovered)
                self.assertIn("sensor.dh_recorder_app_started_at", discovered)
                self.assertIn("button.dh_recorder_app_db_refresh", discovered)
                self.assertIn("button.dh_recorder_app_check_updates", discovered)

    def test_existing_mqtt_identity_and_release_version(self):
        for version in ("0.1.28", "0.1.29"):
            with self.subTest(version=version):
                sync = build_sync_payload(version)
                ha = build_discovery_payload(version)
                self.assertEqual(sync["version"], ha["device"]["sw_version"])
                self.assertEqual(sync["version"], ha["origin"]["sw_version"])
        self.assertEqual(
            SYNC_TOPIC,
            "DigitalHouses/Global/digitalhouses_recorder_app/sync",
        )
        self.assertEqual(
            APP_AVAILABILITY_TOPIC,
            "DigitalHouses/Global/digitalhouses_recorder_app/availability",
        )
        self.assertEqual(
            DISCOVERY_TOPIC,
            "homeassistant/device/digitalhouses_recorder_app/config",
        )

    def test_controls_graphs_and_custom_frontend_cards_preserved(self):
        view = _view_body(CANONICAL.read_text(encoding="utf-8"))
        for contract in (
            "custom:mushroom-template-card",
            "custom:mushroom-chips-card",
            "custom:mushroom-number-card",
            "custom:button-card",
            "custom:mini-graph-card",
            "custom:entity-progress-card-template",
            "button.dh_recorder_app_db_refresh",
            "button.dh_recorder_app_check_updates",
            "perform_action: update.install",
            "perform_action: hassio.app_restart",
            "backup: true",
            "sensor.dh_recorder_app_db_current_hour_records",
            "sensor.dh_recorder_app_db_today_records",
            "sensor.dh_recorder_app_db_top_entities_24h",
            "sensor.dh_recorder_app_db_top_entities_all_time",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, view)
        self.assertGreaterEqual(view.count("aggregate_func: delta"), 2)
        self.assertIn("Нет связи с приложением", view)
        self.assertEqual(view.count("path: recorder\n"), 1)


if __name__ == "__main__":
    unittest.main()
