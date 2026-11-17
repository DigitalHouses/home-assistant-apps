"""Explicit telemetry disable must prevent Plex monitoring runtime from starting."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.app import run
from app.config import load_config


class TelemetryStartupGateTests(unittest.TestCase):
    def test_explicit_false_exits_without_initializing_runtime_or_telemetry(self):
        with tempfile.TemporaryDirectory() as tmp:
            conf = Path(tmp) / "config.ini"
            conf.write_text("[mqtt]\nhost = mqtt.local\n[telemetry]\nenabled = false\n")
            config = load_config(conf)
            self.assertFalse(config.telemetry.enabled)
            with patch("app.app.load_build_info", side_effect=AssertionError("build not needed")), \
                 patch("app.app.verify_proc_visibility", side_effect=AssertionError("monitoring started")), \
                 patch("app.app._telemetry_runner", side_effect=AssertionError("telemetry initialized")):
                with self.assertLogs("digitalhouses_plex_agent", level="ERROR") as output:
                    result = run(config)
            self.assertEqual(result, 0)
            self.assertIn("Телеметрия DigitalHouses отключена", " ".join(output.output))

    def test_default_true_not_blocked_by_explicit_false_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            conf = Path(tmp) / "config.ini"
            conf.write_text("[mqtt]\nhost = mqtt.local\n")
            self.assertTrue(load_config(conf).telemetry.enabled)


if __name__ == "__main__":
    unittest.main()
