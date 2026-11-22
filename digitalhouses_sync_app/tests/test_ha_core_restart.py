"""One checked HA Core restart, not HAOS/Supervisor, for changed Recorder."""
from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from ha_core import CoreAPI
from sync_engine import SyncError


class CoreRestartTests(unittest.TestCase):
    def test_restart_uses_existing_homeassistant_api_and_requires_valid_reply(self):
        api = CoreAPI(token="test-token")
        api._rest = Mock(return_value=[])
        api.restart_core()
        api._rest.assert_called_once_with(
            "services/homeassistant/restart", post=True, timeout=30,
        )
        api._rest = Mock(return_value={"success": True})
        with self.assertRaisesRegex(SyncError, "Invalid Home Assistant restart response"):
            api.restart_core()

    def test_config_check_must_be_explicit_valid(self):
        api = CoreAPI(token="test-token")
        for invalid in ([], {}, {"result": "invalid"}, {"result": "error"}):
            api._rest = Mock(return_value=invalid)
            self.assertFalse(api.check_config())
            api._rest.assert_called_once_with("config/core/check_config", post=True)
        api._rest = Mock(return_value={"result": "valid"})
        self.assertTrue(api.check_config())

    def test_no_additional_supervisor_or_haos_permissions(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        config = (root / "config.yaml").read_text()
        self.assertIn("homeassistant_api: true", config)
        self.assertNotIn("hassio_role: admin", config)
        code = (root / "rootfs/app/ha_core.py").read_text()
        self.assertIn("services/homeassistant/restart", code)
        self.assertNotIn("/supervisor/restart", code)
        self.assertNotIn("/host/reboot", code)


if __name__ == "__main__":
    unittest.main()
