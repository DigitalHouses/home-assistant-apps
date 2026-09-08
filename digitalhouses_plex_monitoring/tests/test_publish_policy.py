import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unittest

from app.models import (
    ActivityState,
    CpuGroupMetrics,
    CpuMetrics,
    MonitorSnapshot,
)
from app.publish_policy import PublishPolicy


def snapshot(
    total: float = 0,
    scanner: float = 0,
    transcoder: float = 0,
    *,
    activity: str = "idle",
    item: str | None = None,
    process_count: int = 1,
    credits: bool = False,
) -> MonitorSnapshot:
    act = ActivityState(
        plex_server_running=True,
        scanner_running=credits,
        credits_detection=credits,
        intro_detection=False,
        thumbnail_generation=False,
        transcoder_running=transcoder > 0,
        activity=activity,
        scanner_actions=("credits",) if credits else (),
        current_item=item,
    )
    return MonitorSnapshot(
        "2026-09-09T00:00:00+00:00",
        act,
        CpuMetrics(
            CpuGroupMetrics(total, total, total),
            CpuGroupMetrics(scanner, scanner, scanner),
            CpuGroupMetrics(transcoder, transcoder, transcoder),
        ),
        process_count,
        "ok",
        None,
    )


class PublishPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = PublishPolicy(5, 80, 60)

    def publish(self, snap, now=0):
        self.policy.mark_published(snap, now)

    def test_startup(self):
        decision = self.policy.evaluate(snapshot(), 0)
        self.assertTrue(decision.publish)
        self.assertIn("startup", decision.reasons)

    def test_item_only_does_not_publish(self):
        self.publish(snapshot(item="a.mkv"), 0)
        decision = self.policy.evaluate(snapshot(item="b.mkv"), 10)
        self.assertFalse(decision.publish)

    def test_process_count_only_does_not_publish(self):
        self.publish(snapshot(process_count=1), 0)
        self.assertFalse(
            self.policy.evaluate(snapshot(process_count=2), 10).publish
        )

    def test_cpu_threshold(self):
        self.publish(snapshot(total=20), 0)
        self.assertFalse(self.policy.evaluate(snapshot(total=24.9), 10).publish)
        self.assertTrue(self.policy.evaluate(snapshot(total=25), 10).publish)

    def test_scanner_cpu_threshold(self):
        self.publish(snapshot(scanner=20), 0)
        self.assertFalse(
            self.policy.evaluate(snapshot(scanner=24.9), 10).publish
        )
        self.assertTrue(
            self.policy.evaluate(snapshot(scanner=25.0), 10).publish
        )

    def test_transcoder_cpu_threshold(self):
        self.publish(snapshot(transcoder=20), 0)
        self.assertFalse(
            self.policy.evaluate(snapshot(transcoder=24.9), 10).publish
        )
        self.assertTrue(
            self.policy.evaluate(snapshot(transcoder=25.0), 10).publish
        )

    def test_zero_transition(self):
        self.publish(snapshot(total=0), 0)
        self.assertTrue(self.policy.evaluate(snapshot(total=0.1), 10).publish)

    def test_high_load_interval(self):
        self.publish(snapshot(total=80), 0)
        self.assertFalse(self.policy.evaluate(snapshot(total=80), 59).publish)
        decision = self.policy.evaluate(snapshot(total=80), 60)
        self.assertTrue(decision.publish)
        self.assertIn("high_load_interval", decision.reasons)

    def test_high_load_crossings(self):
        self.publish(snapshot(total=79), 0)
        enter = self.policy.evaluate(snapshot(total=80), 10)
        self.assertIn("high_load_enter", enter.reasons)
        self.publish(snapshot(total=90), 10)
        exit_ = self.policy.evaluate(snapshot(total=79), 20)
        self.assertIn("high_load_exit", exit_.reasons)

    def test_activity_change(self):
        self.publish(snapshot(), 0)
        changed = snapshot(
            activity="credits_detection",
            credits=True,
            scanner=50,
        )
        self.assertIn(
            "activity_change",
            self.policy.evaluate(changed, 10).reasons,
        )


if __name__ == "__main__":
    unittest.main()
