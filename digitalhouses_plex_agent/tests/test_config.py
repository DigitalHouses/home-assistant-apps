import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tempfile import TemporaryDirectory
import unittest

from app.config import ConfigError, entity_prefix, load_config


class ConfigTests(unittest.TestCase):
    def _write(self, text: str) -> Path:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "app.conf"
        path.write_text(text, encoding="utf-8")
        return path

    def _base(self, extra: str = "") -> str:
        return "[mqtt]\nhost = mqtt.local\n" + extra

    def test_defaults(self):
        config = load_config(self._write(self._base()))
        self.assertEqual(config.general.instance_id, "plex")
        self.assertEqual(config.general.poll_interval_seconds, 10.0)
        self.assertEqual(config.general.cpu_window_seconds, 60.0)
        self.assertEqual(config.telemetry.cpu_change_threshold, 5.0)
        self.assertEqual(config.telemetry.high_load_threshold, 80.0)
        self.assertEqual(
            config.telemetry.high_load_publish_interval_seconds, 60.0
        )

    def test_entity_prefix(self):
        self.assertEqual(entity_prefix("plex"), "dh_plex")
        self.assertEqual(entity_prefix("plex_guest"), "dh_plex_guest")

    def test_invalid_instance_ids(self):
        for value in ("Plex-VM", "_plex", "plex.vm"):
            with self.subTest(value=value):
                path = self._write(
                    f"[general]\ninstance_id = {value}\n[mqtt]\nhost = mqtt\n"
                )
                with self.assertRaises(ConfigError):
                    load_config(path)

    def test_host_required(self):
        with self.assertRaisesRegex(ConfigError, "mqtt.host is required"):
            load_config(self._write("[mqtt]\nhost =\n"))

    def test_password_special_characters(self):
        config = load_config(
            self._write(
                "[mqtt]\nhost = mqtt\npassword = a=b#c;d\n"
            )
        )
        self.assertEqual(config.mqtt.password, "a=b#c;d")


if __name__ == "__main__":
    unittest.main()
