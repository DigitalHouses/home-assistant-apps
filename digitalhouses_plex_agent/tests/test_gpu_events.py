"""GPU events must notify exactly once per verified state transition."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.config import load_config
from app.discovery import build_discovery_payload, build_topics
from app.gpu_events import GpuEventTracker
from app.models import BuildInfo


def gpu(*, status="ok", available=True, driver="bound",
        name="i915", pci="0000:01:00.0", supported=True):
    return {
        "supported": supported,
        "available": available,
        "status": status,
        "driver_status": driver,
        "driver_name": name,
        "pci_address": pci,
    }


class GpuEventTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name) / "gpu_events.json"
        self.now = "2026-10-30T02:00:00+00:00"

    def tracker(self):
        return GpuEventTracker(self.state, now=lambda: self.now)

    def observe_twice(self, tracker, sample):
        self.assertIsNone(tracker.observe(sample))
        return tracker.observe(sample)

    def test_confirmed_gpu_failure_and_recovery_publish_once(self):
        tracker = self.tracker()
        self.assertIsNone(self.observe_twice(tracker, gpu()))
        failing = gpu(status="error", available=False)
        self.assertIsNone(tracker.observe(failing))
        self.assertEqual(tracker.observe(failing), "gpu_unavailable")
        for _ in range(8):
            self.assertIsNone(tracker.observe(failing))
        self.assertEqual(len(tracker.outbox), 1)
        event = tracker.outbox[0]
        self.assertEqual(event["schema_version"], 2)
        self.assertEqual(event["event_type"], "gpu_unavailable")
        self.assertEqual(event["category"], "gpu")
        self.assertEqual(event["driver_name"], "i915")
        self.assertEqual(event["pci_address"], "0000:01:00.0")
        self.assertEqual(event["observed_at"], self.now)
        self.assertEqual(event["previous"]["health"], "ok")
        self.assertEqual(event["current"]["health"], "fault")
        received = []
        self.assertEqual(tracker.flush(lambda x: received.append(x) or True), 1)
        self.assertEqual(len(received), 1)
        self.assertEqual(self.observe_twice(tracker, gpu()), "gpu_restored")
        self.assertEqual(tracker.outbox[0]["event_type"], "gpu_restored")
        self.assertEqual(tracker.outbox[0]["severity"], "info")

    def test_initial_fault_reported_once_then_persisted_across_restart(self):
        tracker = self.tracker()
        failed = gpu(status="error", available=False)
        self.assertEqual(self.observe_twice(tracker, failed), "gpu_unavailable")
        restarted = self.tracker()
        self.assertEqual(restarted.confirmed["health"], "fault")
        self.assertIsNone(self.observe_twice(restarted, failed))
        self.assertEqual(len(restarted.outbox), 1)
        self.assertEqual(restarted.flush(lambda event: False), 0)
        self.assertEqual(len(self.tracker().outbox), 1)
        self.assertEqual(restarted.flush(lambda event: True), 1)
        self.assertEqual(len(self.tracker().outbox), 0)
        self.assertIsNone(self.observe_twice(self.tracker(), failed))

    def test_driver_disconnect_restore_changed_and_prevent_duplicate_gpu_alerts(self):
        tracker = self.tracker()
        self.observe_twice(tracker, gpu())
        sample = gpu(status="error", available=False, driver="not_bound", name=None)
        self.assertEqual(self.observe_twice(tracker, sample), "gpu_driver_unbound")
        self.assertEqual([e["event_type"] for e in tracker.outbox], ["gpu_driver_unbound"])
        self.assertEqual(self.observe_twice(tracker, gpu()), "gpu_driver_restored")
        self.assertEqual(tracker.outbox[-1]["event_type"], "gpu_driver_restored")
        self.assertEqual(self.observe_twice(tracker, gpu(name="xe")), "gpu_driver_changed")
        self.assertEqual(tracker.outbox[-1]["driver_name"], "xe")

    def test_transient_failed_sample_and_unavailable_probe_do_not_alert(self):
        tracker = self.tracker()
        self.observe_twice(tracker, gpu())
        self.assertIsNone(tracker.observe(gpu(status="error", available=False)))
        self.assertIsNone(tracker.observe(gpu()))
        self.assertIsNone(tracker.observe({"supported": True, "status": "starting"}))
        self.assertEqual(tracker.outbox, [])

    def test_no_intel_gpu_initially_is_not_a_problem(self):
        tracker = self.tracker()
        sample = gpu(supported=False, status="unsupported", driver="not_detected",
                     available=False, name=None, pci=None)
        self.assertIsNone(self.observe_twice(tracker, sample))
        self.assertEqual(tracker.outbox, [])

    def test_persistent_error_after_reconnect_does_not_refire(self):
        tracker = self.tracker()
        failed = gpu(status="error", available=False)
        self.observe_twice(tracker, failed)
        self.assertEqual(tracker.flush(lambda e: True), 1)
        tracker = self.tracker()
        self.assertIsNone(self.observe_twice(tracker, failed))
        self.assertEqual(tracker.outbox, [])

    def test_mqtt_discovery_event_is_same_device_and_diagnostic_nonretained(self):
        config_file = Path(self.tmp.name) / "app.conf"
        config_file.write_text("[mqtt]\nhost = mqtt\n")
        config = load_config(config_file)
        topics = build_topics(config)
        component = build_discovery_payload(
            config, BuildInfo("0.8.5", "test", "abcdef")
        )["components"]["diagnostic_event"]
        self.assertEqual(
            component["default_entity_id"], "event.dh_plex_agent_gpu_diagnostic"
        )
        self.assertEqual(component["state_topic"], topics.diagnostic_event)
        self.assertEqual(component["qos"], 1)
        self.assertEqual(component["platform"], "event")
        self.assertEqual(len(component["event_types"]), 5)
        self.assertEqual(
            topics.diagnostic_event,
            "DigitalHouses/Global/digitalhouses_plex_agent/events/diagnostic",
        )


if __name__ == "__main__":
    unittest.main()
