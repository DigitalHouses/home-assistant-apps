import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dh_presence.operations import Operations, find_latest_release, is_newer


class TestOperations(unittest.TestCase):
    def test_stable_release_filters_other_products_and_prereleases(self):
        releases = [
            {"tag_name": "digitalhouses_presence_app-v0.1.5", "draft": False, "prerelease": False},
            {"tag_name": "digitalhouses_presence_app-v0.2.0", "draft": True, "prerelease": False},
            {"tag_name": "digitalhouses_presence_app-v0.1.10", "draft": False, "prerelease": False},
            {"tag_name": "digitalhouses_presence_app-v0.3.0", "draft": False, "prerelease": True},
            {"tag_name": "digitalhouses_internet_app-v9.0.0", "draft": False, "prerelease": False},
        ]
        self.assertEqual(find_latest_release(releases), "0.1.10")
        self.assertIsNone(find_latest_release([]))
        self.assertTrue(is_newer("0.1.9", "0.1.10"))
        self.assertFalse(is_newer("0.1.10", "0.1.9"))
        self.assertIsNone(is_newer("0.1.9", None))

    def test_real_manual_refresh_lifecycle_and_persistent_last_refresh(self):
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "last-refresh.json")
            operation = Operations(path)
            self.assertIsNone(operation.snapshot()["last_refresh"])
            self.assertTrue(operation.begin("refresh"))
            self.assertFalse(operation.begin("refresh"))
            self.assertEqual(operation.snapshot()["refresh_state"], "updating")
            operation.finish(refresh_succeeded=True)
            self.assertEqual(operation.snapshot()["card"]["state"], "success")
            self.assertEqual(operation.snapshot()["refresh_state"], "idle")
            self.assertIsNotNone(operation.snapshot()["last_refresh"])
            restarted = Operations(path)
            self.assertEqual(restarted.snapshot()["card"]["state"], "idle")
            self.assertEqual(restarted.snapshot()["last_refresh"], operation.last_refresh)

    def test_failure_does_not_advance_timestamp_and_is_sticky(self):
        with tempfile.TemporaryDirectory() as d:
            op = Operations(str(Path(d) / "last-refresh.json"))
            op.begin("refresh")
            op.finish("Source not fresh")
            self.assertEqual(op.snapshot()["card"]["state"], "error")
            self.assertEqual(op.snapshot()["refresh_state"], "error")
            self.assertIsNone(op.snapshot()["last_refresh"])
            self.assertFalse(op.tick())
            self.assertEqual(op.snapshot()["card"]["state"], "error")
            self.assertTrue(op.begin("check"))
            op.finish()
            self.assertIsNone(op.snapshot()["last_refresh"])

    def test_success_resets_after_five_seconds_without_timers_in_mqtt(self):
        with tempfile.TemporaryDirectory() as d:
            op = Operations(str(Path(d) / "last-refresh.json"))
            with patch("dh_presence.operations.time.monotonic", side_effect=[100, 102, 102, 106, 107.1]):
                op.begin("check")
                op.finish()
                self.assertFalse(op.tick())
                self.assertTrue(op.tick())
            self.assertEqual(op.snapshot()["card"]["state"], "idle")


if __name__ == "__main__":
    unittest.main()
