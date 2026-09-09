from pathlib import Path
import unittest

APP = (Path(__file__).resolve().parents[1] / "app" / "app.py").read_text(encoding="utf-8")


class AppPlexApiContractTests(unittest.TestCase):
    def test_runtime_is_integrated_without_replacing_process_collector(self):
        self.assertIn("PlexApiRuntime", APP)
        self.assertIn("api_runtime.collect", APP)
        self.assertIn("mqtt.set_plex_api_available", APP)
        self.assertIn("mqtt.set_discovery_payload", APP)
        self.assertIn("build_state_payload", APP)
        self.assertIn("collect_raw_processes", APP)

    def test_api_payload_is_merged_before_mqtt_publish(self):
        self.assertIn("payload.update(api_runtime.payload())", APP)


if __name__ == "__main__":
    unittest.main()
