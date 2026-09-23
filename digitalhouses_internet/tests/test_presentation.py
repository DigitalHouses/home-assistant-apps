from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = APP_ROOT / "rootfs" / "app"
sys.path.insert(0, str(APP_DIR))

from discovery import build_discovery_payload


ENTITY_RE = re.compile(
    r"\b(?:sensor|binary_sensor|number|button|event)\."
    r"dh_internet_app_[a-z0-9_]+"
)


class PresentationTests(unittest.TestCase):
    def test_examples_reference_only_discovered_entities(self) -> None:
        payload = build_discovery_payload(
            "0.1.0",
            traffic_enabled=True,
            wan_enabled=True,
            download_rate_enabled=True,
            upload_rate_enabled=True,
        )
        discovered = {
            component["default_entity_id"]
            for component in payload["components"].values()
            if "default_entity_id" in component
        }
        paths = [
            APP_ROOT
            / "examples"
            / "packages"
            / "dh_internet_app_global_package.yaml",
            APP_ROOT
            / "examples"
            / "packages"
            / "dh_internet_app_notification_package.yaml",
            APP_ROOT
            / "examples"
            / "packages"
            / "locales"
            / "dh_internet_app_notification_package_ru.yaml",
            APP_ROOT
            / "examples"
            / "lovelace"
            / "dh_internet_app_dashboard.yaml",
        ]
        for path in paths:
            content = path.read_text(encoding="utf-8")
            references = set(ENTITY_RE.findall(content))
            missing = sorted(references - discovered)
            self.assertEqual(
                missing,
                [],
                f"{path.relative_to(APP_ROOT)} references unknown entities",
            )

    def test_examples_contain_no_legacy_speedtest_entities(self) -> None:
        examples = APP_ROOT / "examples"
        for path in examples.rglob("*.yaml"):
            content = path.read_text(encoding="utf-8")
            self.assertNotIn("sensor.internet_speed_", content)
            self.assertNotIn("binary_sensor.internet_", content)
            self.assertNotIn("number.internet_speed_", content)
            self.assertNotIn("button.internet_speed_", content)


if __name__ == "__main__":
    unittest.main()
