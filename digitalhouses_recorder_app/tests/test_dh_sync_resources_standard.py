"""Recorder App's published YAML contract for automatic DH Sync 0.4.

DH Sync admits sources by the DigitalHouses GitHub owner alone, discovers
canonical YAML in the default branch, and synchronizes it without Apply.
The App's release version is metadata, not a YAML compatibility gate.
"""
from __future__ import annotations

import hashlib
import re
import sys
import unittest
from pathlib import Path
from urllib.parse import urlsplit

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "rootfs" / "app"))

from discovery import (  # noqa: E402
    APP_AVAILABILITY_TOPIC,
    DISCOVERY_TOPIC,
    build_discovery_payload,
)
from sync_discovery import (  # noqa: E402
    PRODUCT_PATH,
    REPOSITORY_URL,
    SYNC_TOPIC,
    build_sync_payload,
)

CANONICAL = APP / "dashboards" / "ru" / "10_recorder.yaml"
BASELINE = APP / "examples" / "lovelace" / "dh_recorder_app_dashboard.yaml"
BASELINE_GIT_BLOB_SHA1 = "45dd279a425c0165deccdb0b53e6d9fe6b37a8af"
EXTERNAL_ACTIONS = {"button.press", "update.install"}
SUPERVISOR_ENTITIES = {"update.digitalhouses_recorder_app_update"}
ENTITY_REFERENCE = re.compile(
    r"\b(?:sensor|binary_sensor|button|number|event|update)\.[a-z0-9_]+\b"
)


def _git_blob_sha1(raw: bytes) -> str:
    prefix = b"blob " + str(len(raw)).encode("ascii") + b"\0"
    return hashlib.sha1(prefix + raw).hexdigest()


def _view_body(raw: str) -> str:
    for index, line in enumerate(raw.splitlines(keepends=True)):
        if line.strip() and not line.startswith("#"):
            return "".join(raw.splitlines(keepends=True)[index:])
    raise AssertionError("Canonical dashboard has no Lovelace body")


def _app_version() -> str:
    config = (APP / "config.yaml").read_text(encoding="utf-8")
    match = re.search(r"(?m)^version:\s*['\"]?(\d+\.\d+\.\d+)['\"]?\s*$", config)
    if match is None:
        raise AssertionError("Recorder release version missing")
    return match.group(1)


class RecorderDHSynchronizationStandardTests(unittest.TestCase):
    def test_canonical_standalone_ru_view_is_automatically_discoverable(self):
        self.assertEqual(
            CANONICAL.relative_to(APP).as_posix(),
            "dashboards/ru/10_recorder.yaml",
        )
        view = CANONICAL.read_text(encoding="utf-8")
        self.assertTrue(view.startswith("# DH-View: dh_recorder_app\n"))
        self.assertIn("# DH-View-Version: 1.0.0\n", view)
        self.assertNotIn("# DH-Compatible-App:", view)
        self.assertNotIn("# DH-Compatible-Agent:", view)
        body = _view_body(view)
        self.assertTrue(body.startswith(
            "title: DH Recorder\npath: recorder\nicon: mdi:database\n"
            "type: sections\nmax_columns: 4\nsections:\n"
        ))
        self.assertEqual(body.count("path: recorder\n"), 1)
        self.assertNotIn("\nlovelace:", body)
        self.assertNotIn("\nviews:", body)
        self.assertNotIn("192.168.", body)

    def test_published_dashboard_body_preserves_the_maintained_example(self):
        original = BASELINE.read_bytes()
        self.assertEqual(_git_blob_sha1(original), BASELINE_GIT_BLOB_SHA1)
        self.assertEqual(
            _view_body(CANONICAL.read_text(encoding="utf-8")).encode("utf-8"),
            original,
        )
        self.assertTrue(original.endswith(b"cards: []\nbadges: []\n"))

    def test_product_announces_digitalhouses_owner_and_product_path(self):
        parsed = urlsplit(REPOSITORY_URL)
        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.netloc, "github.com")
        self.assertEqual(parsed.path.split("/")[1], "DigitalHouses")
        self.assertEqual(parsed.path, "/DigitalHouses/home-assistant-apps")
        self.assertEqual(PRODUCT_PATH, "digitalhouses_recorder_app")
        version = _app_version()
        claim = build_sync_payload(version)
        self.assertEqual(claim["repository"], REPOSITORY_URL)
        self.assertEqual(claim["product_path"], PRODUCT_PATH)
        self.assertEqual(claim["version"], version)
        self.assertEqual(claim["product_id"], "digitalhouses_recorder_app")
        self.assertEqual(SYNC_TOPIC, "DigitalHouses/Global/digitalhouses_recorder_app/sync")
        self.assertEqual(
            APP_AVAILABILITY_TOPIC,
            "DigitalHouses/Global/digitalhouses_recorder_app/availability",
        )
        self.assertEqual(
            DISCOVERY_TOPIC,
            "homeassistant/device/digitalhouses_recorder_app/config",
        )

    def test_dashboard_entities_match_current_mqtt_discovery(self):
        references = set(ENTITY_REFERENCE.findall(
            _view_body(CANONICAL.read_text(encoding="utf-8"))
        ))
        version = _app_version()
        discovery = build_discovery_payload(version, include_storage=True)
        discovered = {
            component["default_entity_id"]
            for component in discovery["components"].values()
            if "default_entity_id" in component
        }
        self.assertEqual(references - discovered, SUPERVISOR_ENTITIES | EXTERNAL_ACTIONS)
        self.assertIn("sensor.dh_recorder_app_version", discovered)
        self.assertIn("sensor.dh_recorder_app_started_at", discovered)
        self.assertIn("button.dh_recorder_app_db_refresh", discovered)
        self.assertIn("button.dh_recorder_app_check_updates", discovered)
        self.assertEqual(
            discovery["device"]["sw_version"],
            build_sync_payload(version)["version"],
        )

    def test_existing_controls_graphs_and_frontend_requirements_preserved(self):
        body = _view_body(CANONICAL.read_text(encoding="utf-8"))
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
                self.assertIn(contract, body)
        self.assertGreaterEqual(body.count("aggregate_func: delta"), 2)
        self.assertIn("Нет связи с приложением", body)


if __name__ == "__main__":
    unittest.main()
