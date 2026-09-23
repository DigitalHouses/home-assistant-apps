from __future__ import annotations

import sys
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "rootfs" / "app"
sys.path.insert(0, str(APP_DIR))

from quality import evaluate_performance, normalize_thresholds, set_threshold


class QualityTests(unittest.TestCase):
    def test_defaults(self) -> None:
        self.assertEqual(
            normalize_thresholds({}),
            {
                "minimum_download_mbps": 10,
                "minimum_upload_mbps": 10,
                "maximum_ping_ms": 200,
            },
        )

    def test_evaluation(self) -> None:
        result = evaluate_performance(
            {
                "tested_at": "2026-09-23T10:00:00+00:00",
                "download_mbps": 9,
                "upload_mbps": 20,
                "ping_ms": 250,
            },
            {
                "minimum_download_mbps": 10,
                "minimum_upload_mbps": 10,
                "maximum_ping_ms": 200,
            },
        )
        self.assertTrue(result["available"])
        self.assertTrue(result["low_download"])
        self.assertFalse(result["low_upload"])
        self.assertTrue(result["high_ping"])
        self.assertTrue(result["performance_problem"])
        self.assertEqual(
            result["problem_reasons"],
            ["low_download", "high_ping"],
        )

    def test_threshold_range(self) -> None:
        with self.assertRaises(ValueError):
            set_threshold(normalize_thresholds({}), "maximum_ping_ms", 0)


if __name__ == "__main__":
    unittest.main()
