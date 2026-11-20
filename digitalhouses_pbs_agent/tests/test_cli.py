"""Native PBS Agent management behavior; offline, no broker or PBS needed."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.cli import change_config
from app.config import load_config


TEMPLATE = """# Admin-owned native config
[general]
instance_id = pbs_home
log_level = info
[mqtt]
host = broker.home
port = 1883
password =
[pbs]
url = https://127.0.0.1:8007
token_id = monitor@pbs!readonly
token_secret_file = /tmp/test-pbs-secret
insecure_localhost = true
datastores = pbs-home
[monitor]
poll_seconds = 300
warning_percent = 80
critical_percent = 90
"""


class CLIManagementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "agent.conf"
        self.path.write_text(TEMPLATE, encoding="utf-8")

    def test_native_set_updates_two_settings_in_one_atomic_write(self):
        with patch("app.cli.subprocess.run") as restart:
            changed = change_config(self.path, ["mqtt_port=1884", "monitor_poll_seconds=180"])
            self.assertEqual(changed, "CHANGED")
            self.assertEqual(load_config(self.path).mqtt_port, 1884)
            self.assertEqual(load_config(self.path).poll_seconds, 180)
            restart.assert_not_called()
        self.assertIn("# Admin-owned native config", self.path.read_text("utf-8"))

    def test_idempotent_set_never_restarts(self):
        with patch("app.cli.subprocess.run") as restart:
            self.assertEqual(change_config(self.path, ["mqtt_port=1883"]), "UNCHANGED")
            restart.assert_not_called()
        self.assertEqual(self.path.read_text("utf-8"), TEMPLATE)

    def test_invalid_batch_rolls_back(self):
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            change_config(self.path, ["mqtt_host=valid.example", "monitor_warning_percent=95"])
        self.assertEqual(self.path.read_bytes(), before)
        with self.assertRaises(ValueError):
            change_config(self.path, ["mqtt_port=1885", "mqtt_port=1886"])
        self.assertEqual(self.path.read_bytes(), before)

    def test_credentials_cannot_be_exposed_in_cli_arguments(self):
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            change_config(self.path, ["mqtt_password=supersecret"])
        self.assertEqual(self.path.read_bytes(), before)

    def test_invalid_loopback_tls_change_rolls_back(self):
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            change_config(self.path, ["pbs_url=https://192.0.2.14:8007"])
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
