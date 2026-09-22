import sys
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "rootfs" / "app"
sys.path.insert(0, str(APP))

from core import BucketAccumulator, build_account_state, slugify


class CoreTests(unittest.TestCase):
    def test_accumulator_counts_current_files_versions_and_storage(self):
        acc = BucketAccumulator("b1", "ha-backups", "allPrivate")
        for item in [
            {"fileName": "a.tar", "action": "upload", "contentLength": 100},
            {"fileName": "a.tar", "action": "upload", "contentLength": 80},
            {"fileName": "b.tar", "action": "hide", "contentLength": 0},
            {"fileName": "b.tar", "action": "upload", "contentLength": 50},
        ]:
            acc.consume(item)

        result = acc.result()
        self.assertEqual(result["storage_bytes"], 230)
        self.assertEqual(result["file_count"], 1)
        self.assertEqual(result["version_count"], 3)
        self.assertEqual(result["old_version_count"], 2)
        self.assertEqual(result["hide_marker_count"], 1)

    def test_account_total_is_sum_of_bucket_bytes(self):
        state = build_account_state(
            [
                {"bucket_id": "a", "storage_bytes": 100},
                {"bucket_id": "b", "storage_bytes": 200},
            ],
            app_version="0.1.0",
            started_at="2026-09-22T00:00:00+00:00",
            updated_at="2026-09-22T01:00:00+00:00",
        )
        self.assertEqual(state["total_bytes"], 300)
        self.assertEqual(state["bucket_count"], 2)

    def test_slugify_is_entity_safe(self):
        self.assertEqual(slugify("HA Backups-01"), "ha_backups_01")


if __name__ == "__main__":
    unittest.main()
