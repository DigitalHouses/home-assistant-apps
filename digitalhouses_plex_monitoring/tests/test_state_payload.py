import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unittest

from app.models import (
    ActivityState,
    BuildInfo,
    CpuGroupMetrics,
    CpuMetrics,
    MonitorSnapshot,
    build_state_payload,
)


class StatePayloadTests(unittest.TestCase):
    def test_payload(self):
        snapshot = MonitorSnapshot(
            "2026-09-09T00:00:00+00:00",
            ActivityState(
                True, True, True, False, False, False,
                "credits_detection", ("credits",), "movie.ts",
            ),
            CpuMetrics(
                CpuGroupMetrics(106.04, 80.02, 109.99),
                CpuGroupMetrics(100, 70, 105),
                CpuGroupMetrics(0, 0, 0),
            ),
            3,
            "ok",
            None,
        )
        payload = build_state_payload(
            snapshot,
            BuildInfo("0.1.0", "main", "0123456789abcdef"),
        )
        self.assertEqual(payload["cpu"], 106.0)
        self.assertEqual(payload["current_item"], "movie.ts")
        self.assertEqual(payload["scanner_actions"], "credits")
        self.assertEqual(payload["build_commit_short"], "0123456789ab")
        expected = {
            "collected_at",
            "activity",
            "current_item",
            "server_running",
            "scanner_running",
            "credits_detection",
            "intro_detection",
            "thumbnail_generation",
            "transcoder_running",
            "scanner_actions",
            "process_count",
            "collector_status",
            "cpu",
            "cpu_avg",
            "cpu_max",
            "scanner_cpu",
            "scanner_cpu_avg",
            "scanner_cpu_max",
            "transcoder_cpu",
            "transcoder_cpu_avg",
            "transcoder_cpu_max",
            "last_refresh",
            "build_version",
            "build_source",
            "build_commit",
            "build_commit_short",
        }
        self.assertEqual(set(payload), expected)


if __name__ == "__main__":
    unittest.main()
