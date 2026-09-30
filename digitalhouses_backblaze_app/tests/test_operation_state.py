import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "rootfs" / "app"))

from operation_status import operation_payload
from runtime_state import RuntimeStateError, load_last_refresh, save_last_refresh


class OperationStatusTests(unittest.TestCase):
    def test_operation_payload_matches_manual_refresh_standard(self):
        payload = operation_payload(
            "error",
            started_at="2026-09-30T10:00:00+00:00",
            finished_at="2026-09-30T10:00:02+00:00",
            duration_seconds=2.1236,
            error="failure",
        )
        self.assertEqual(
            payload,
            {
                "state": "error",
                "started_at": "2026-09-30T10:00:00+00:00",
                "finished_at": "2026-09-30T10:00:02+00:00",
                "duration_seconds": 2.124,
                "error": "failure",
            },
        )

    def test_operation_payload_rejects_unknown_state(self):
        with self.assertRaisesRegex(ValueError, "unsupported operation state"):
            operation_payload("running")


class RuntimeStateTests(unittest.TestCase):
    def test_missing_runtime_state_means_no_manual_refresh_yet(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "runtime_state.json"
            self.assertIsNone(load_last_refresh(path))

    def test_last_refresh_round_trip(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "runtime_state.json"
            value = "2026-09-30T10:00:00+00:00"
            save_last_refresh(value, path)
            self.assertEqual(load_last_refresh(path), value)

    def test_corrupt_runtime_state_fails_visibly(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "runtime_state.json"
            path.write_text("{broken", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeStateError, "not valid JSON"):
                load_last_refresh(path)


if __name__ == "__main__":
    unittest.main()
