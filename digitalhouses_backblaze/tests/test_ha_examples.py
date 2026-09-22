import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "examples/packages/dh_app_backblaze_package.yaml"
DASHBOARD = ROOT / "examples/lovelace/dh_app_backblaze_dashboard.yaml"


class HomeAssistantExamplesTests(unittest.TestCase):
    def test_recorder_package_is_narrow(self):
        text = PACKAGE.read_text(encoding="utf-8")

        self.assertIn("dh_app_backblaze_package:", text)
        self.assertIn("recorder:", text)
        self.assertIn("sensor.dh_backblaze_storage_used", text)
        self.assertIn("sensor.dh_backblaze_files", text)

        recorder_section = text.split("recorder:", 1)[1]
        self.assertEqual(
            recorder_section.count("- sensor."),
            2,
        )
        self.assertNotIn("sensor.dh_backblaze_bucket_count", recorder_section)
        self.assertNotIn("sensor.dh_backblaze_versions", recorder_section)

    def test_dashboard_uses_daily_total_used_bar_chart(self):
        text = DASHBOARD.read_text(encoding="utf-8")

        self.assertIn("entity: sensor.dh_backblaze_storage_used", text)
        self.assertIn("name: Total used by day", text)
        self.assertIn("hours_to_show: 720", text)
        self.assertIn("group_by: date", text)
        self.assertIn("aggregate_func: max", text)
        self.assertIn("graph: bar", text)

    def test_dashboard_uses_account_totals_and_dynamic_buckets(self):
        text = DASHBOARD.read_text(encoding="utf-8")

        for entity_id in (
            "sensor.dh_backblaze_storage_used",
            "sensor.dh_backblaze_files",
            "sensor.dh_backblaze_bucket_count",
            "sensor.dh_backblaze_versions",
        ):
            self.assertIn(entity_id, text)

        self.assertIn("custom:auto-entities", text)
        self.assertIn("sensor.dh_backblaze_*_used", text)
        self.assertIn("sensor.dh_backblaze_*_files", text)
        self.assertIn("sensor.dh_backblaze_*_versions", text)


if __name__ == "__main__":
    unittest.main()
