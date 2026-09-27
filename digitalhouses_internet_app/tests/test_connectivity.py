from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

APP_DIR = Path(__file__).resolve().parents[1] / "rootfs" / "app"
sys.path.insert(0, str(APP_DIR))

from connectivity import (\n    CLOUDFLARE_PROBE,\n    GOOGLE_PROBE,\n    ConnectivityProbeError,\n    ping_host,\n    sample,\n)


class ConnectivityTests(unittest.TestCase):
    def test_internet_is_up_when_either_probe_answers(self) -> None:
        answers = {
            GOOGLE_PROBE: False,
            CLOUDFLARE_PROBE: True,
            "192.168.1.1": True,
        }
        with patch(
            "connectivity.ping_host",
            side_effect=lambda host, timeout: answers[host],
        ):
            result = sample("192.168.1.1", 2)
        self.assertTrue(result.internet_up)
        self.assertFalse(result.google_up)
        self.assertTrue(result.cloudflare_up)
        self.assertTrue(result.router_up)

    def test_ping_execution_error_is_not_reported_as_down(self) -> None:
        with patch("connectivity.subprocess.run", side_effect=OSError("missing ping")):
            with self.assertRaises(ConnectivityProbeError):
                ping_host("192.0.2.1", 2)

    def test_ping_process_timeout_is_not_reported_as_down(self) -> None:
        import subprocess

        with patch(
            "connectivity.subprocess.run",
            side_effect=subprocess.TimeoutExpired("ping", 4),
        ):
            with self.assertRaises(ConnectivityProbeError):
                ping_host("192.0.2.1", 2)

    def test_internet_is_down_only_when_both_probes_fail(self) -> None:
        answers = {
            GOOGLE_PROBE: False,
            CLOUDFLARE_PROBE: False,
            "192.168.1.1": True,
        }
        with patch(
            "connectivity.ping_host",
            side_effect=lambda host, timeout: answers[host],
        ):
            result = sample("192.168.1.1", 2)
        self.assertFalse(result.internet_up)
        self.assertFalse(result.google_up)
        self.assertFalse(result.cloudflare_up)
        self.assertTrue(result.router_up)


if __name__ == "__main__":
    unittest.main()
