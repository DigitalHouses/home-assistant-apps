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

NOTIFICATION_EVENTS = (
    "connection_lost",
    "connection_restored",
    "recovery_action",
    "recovery_stopped",
    "recovery_exhausted",
    "recovery_error",
    "speedtest_failed",
    "performance_problem_started",
    "performance_problem_recovered",
    "performance_problem_updated",
)

NOTIFICATION_REQUIRED_FIELDS = {
    "connection_lost": ("router_up", "attempts"),
    "connection_restored": ("duration_seconds",),
    "recovery_action": ("cycle", "target", "action", "entity_id"),
    "recovery_stopped": ("reason",),
    "recovery_exhausted": ("cycles", "cooldown_seconds"),
    "recovery_error": ("error",),
    "speedtest_failed": ("reason",),
    "performance_problem_started": (
        "reasons",
        "download_mbps",
        "upload_mbps",
        "ping_ms",
        "minimum_download_mbps",
        "minimum_upload_mbps",
        "maximum_ping_ms",
    ),
    "performance_problem_recovered": (
        "previous_reasons",
        "download_mbps",
        "upload_mbps",
        "ping_ms",
    ),
    "performance_problem_updated": (
        "previous_reasons",
        "reasons",
        "download_mbps",
        "upload_mbps",
        "ping_ms",
    ),
}


def notification_paths() -> tuple[Path, Path]:
    return (
        APP_ROOT
        / "examples"
        / "packages"
        / "dh_internet_app_notification_local_package.yaml",
        APP_ROOT
        / "examples"
        / "packages"
        / "locales"
        / "ru"
        / "dh_internet_app_notification_local_package.yaml",
    )


class PresentationTests(unittest.TestCase):
    def test_legacy_notification_envelope_packages_are_removed(self) -> None:
        legacy_paths = (
            APP_ROOT / "examples" / "packages" / "dh_internet_app_notification_package.yaml",
            APP_ROOT
            / "examples"
            / "packages"
            / "locales"
            / "ru"
            / "dh_internet_app_notification_package.yaml",
        )
        for path in legacy_paths:
            self.assertFalse(path.exists(), f"legacy notification package still exists: {path}")

    def test_examples_reference_only_discovered_entities(self) -> None:
        payload = build_discovery_payload(
            "0.1.5",
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
            *notification_paths(),
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

    def test_notification_locales_use_direct_flow(self) -> None:
        en, ru = [
            path.read_text(encoding="utf-8")
            for path in notification_paths()
        ]
        for content in (en, ru):
            self.assertIn(
                "dh_internet_app_notification_local_package:\n",
                content,
            )
            self.assertIn(
                "- id: dh_internet_app_notifications",
                content,
            )
            self.assertIn(
                "entity_id: event.dh_internet_app_event",
                content,
            )
            self.assertIn("trigger: event.received", content)
            self.assertIn("condition: trigger", content)
            self.assertIn("trigger.to_state.attributes", content)
            for event_type in NOTIFICATION_EVENTS:
                self.assertIn(f"- {event_type}", content)
                self.assertIn(f"id: {event_type}", content)

            for forbidden in (
                "event: dh_internet_app_notification",
                "notification_schema_version",
                "contract_error",
                "failure_class",
                "machine_schema_version",
                "attrs.schema_version",
                "is mapping",
            ):
                self.assertNotIn(forbidden, content)

        self.assertIn("action: persistent_notification.create", en)
        self.assertNotIn("script.write2log", en)
        self.assertIn("action: script.write2log", ru)

    def test_notification_text_reads_required_machine_fields_directly(self) -> None:
        for path in notification_paths():
            content = path.read_text(encoding="utf-8")
            for event_type, fields in NOTIFICATION_REQUIRED_FIELDS.items():
                self.assertIn(f"id: {event_type}", content)
                for field in fields:
                    self.assertIn(
                        f"trigger.to_state.attributes.{field}",
                        content,
                        f"{path.name}: {event_type} does not use {field}",
                    )
            self.assertNotIn("default(", content)
            self.assertNotIn("int(0)", content)

    def test_machine_event_producer_contains_no_presentation_fields(self) -> None:
        source = (APP_DIR / "app.py").read_text(encoding="utf-8")
        start = source.index("    def _event(")
        end = source.index("    def _set_recovery_state(", start)
        event_method = source[start:end]
        for forbidden in (
            '"title"',
            '"message"',
            '"summary"',
            '"emoji"',
            '"status_ru"',
            '"status_en"',
        ):
            self.assertNotIn(forbidden, event_method)

    def test_optional_router_and_traffic_cards_hide_unavailable(self) -> None:
        dashboard = (
            APP_ROOT
            / "examples"
            / "lovelace"
            / "dh_internet_app_dashboard.yaml"
        ).read_text(encoding="utf-8")
        router_section = dashboard.split("title: Router telemetry", 1)[1].split(
            "title: Traffic", 1
        )[0]
        traffic_section = dashboard.split("title: Traffic", 1)[1].split(
            "- type: conditional", 1
        )[0]
        for section in (router_section, traffic_section):
            self.assertIn('state: "unavailable"', section)
            self.assertIn('state: "unknown"', section)
        self.assertNotIn("heading: Router & Traffic", dashboard)
        self.assertIn("condition: numeric_state", dashboard)

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
