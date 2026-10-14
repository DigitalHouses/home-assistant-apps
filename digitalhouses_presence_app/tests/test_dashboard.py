"""Presence dashboard uses existing entities without inventing runtime commands."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
CARD = ROOT / "examples/lovelace/presence_app_card_ru.yaml"
DASHBOARD = ROOT / "examples/lovelace/dh_presence_app_dashboard.yaml"


class LovelaceCardTests(unittest.TestCase):
    def test_card_uses_existing_presence_mqtt_entities(self):
        code = CARD.read_text(encoding="utf-8")
        for entity in (
            "binary_sensor.dh_presence_app_residents_home",
            "select.dh_presence_app_mode",
            "sensor.dh_presence_app_version",
            "event.dh_presence_app_event",
            "sensor.dh_presence_app_started_at",
        ):
            self.assertIn(entity, code)
        self.assertIn("attributes?.residents", code)
        self.assertIn("sensor.dh_presence_app_' + key + '_distance", code)
        self.assertIn("binary_sensor.dh_presence_app_' + key + '_gps_home", code)

    def test_no_fabricated_action_service_or_sensor(self):
        text = CARD.read_text(encoding="utf-8")
        for forbidden in (
            "sensor.dh_presence_app_card",
            "button.dh_presence_app_refresh",
            "button.dh_presence_app_check_updates",
            "hassio.app_restart",
            "update.install",
        ):
            self.assertNotIn(forbidden, text)

    def test_read_only_header_and_true_mode_select(self):
        text = CARD.read_text(encoding="utf-8")
        self.assertIn("action: none", text)
        self.assertIn("type: select-options", text)
        self.assertIn("mode === 'wifi'", text)
        self.assertIn("Последнее подтверждение", text)

    def test_dashboard_embeds_canonical_card_without_drift(self):
        card = CARD.read_text(encoding="utf-8")
        dashboard = DASHBOARD.read_text(encoding="utf-8")
        normalized_card = "\n".join("      " + line for line in card.split("\n") if line.strip() and not line.startswith("#"))
        self.assertIn(normalized_card, dashboard)
