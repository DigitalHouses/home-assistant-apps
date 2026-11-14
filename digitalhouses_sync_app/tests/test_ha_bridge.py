import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from ha_bridge import HAWebSocketBridge
from storage_migration import MigrationError


class FakeSocket:
    def __init__(self, replies):
        self.replies = list(replies)
        self.sent = []
    def recv(self):
        return self.replies.pop(0)
    def send(self, data):
        self.sent.append(data)
    def close(self):
        pass


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        (self.home / ".storage").mkdir()
        self.storage_file = self.home / ".storage/lovelace.dashboard_system"
        self.storage_file.write_text('{"data":{"config":{"views":[]}}}')
        self.bridge = HAWebSocketBridge(
            base_url="http://homeassistant:8123",
            admin_token="unit-test-only",
            home=self.home,
            storage_file=".storage/lovelace.dashboard_system",
        )

    def test_persisted_storage_is_parsed_without_writes(self):
        self.assertEqual(self.bridge.read_persisted_storage("dashboard-system"), {"views":[]})

    def test_invalid_storage_path_rejected(self):
        with self.assertRaises(MigrationError):
            HAWebSocketBridge(
                base_url="http://localhost:8123",
                admin_token="unit-test",
                home=self.home,
                storage_file="../configuration.yaml",
            )

    def test_symlink_storage_file_rejected(self):
        other = self.home / "other"
        other.write_text("{}")
        self.storage_file.unlink()
        self.storage_file.symlink_to(other)
        with self.assertRaises(MigrationError):
            self.bridge.read_persisted_storage("dashboard-system")

    def test_ha_url_with_credentials_rejected(self):
        with self.assertRaises(MigrationError):
            HAWebSocketBridge(
                base_url="http://username:pass@host:8123",
                admin_token="test",
                home=self.home,
                storage_file=".storage/lovelace.dashboard_system",
            )

    def test_empty_admin_token_rejected(self):
        with self.assertRaises(MigrationError):
            HAWebSocketBridge(
                base_url="http://host:8123",
                admin_token="",
                home=self.home,
                storage_file=".storage/lovelace.dashboard_system",
            )

    def test_invalid_sensor_version_rejected(self):
        with patch.object(self.bridge, "_ws", return_value=[
            {"entity_id": "sensor.dh_plex_agent_version", "state": "unavailable"}
        ]):
            with self.assertRaises(MigrationError):
                self.bridge.read_plex_agent_version()

    def test_version_observation(self):
        with patch.object(self.bridge, "_ws", return_value=[
            {"entity_id": "sensor.dh_plex_agent_version", "state": "0.8.17"}
        ]):
            self.assertEqual(self.bridge.read_plex_agent_version(), "0.8.17")

    def test_ws_save_command_uses_official_type(self):
        with patch.object(self.bridge, "_ws", return_value=None) as ws:
            self.bridge.save_storage("dashboard-system", {"views": []})
            ws.assert_called_once_with({
                "type": "lovelace/config/save",
                "url_path": "dashboard-system",
                "config": {"views": []},
            })

    def test_check_config_requires_explicit_valid(self):
        response = MagicMock()
        response.status = 200
        response.read.return_value = b'{"result":"invalid","errors":"test"}'
        response.__enter__.return_value = response
        with patch("urllib.request.urlopen", return_value=response):
            self.assertFalse(self.bridge.check_config())


if __name__ == "__main__":
    unittest.main()
