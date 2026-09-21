from pathlib import Path
import unittest

APP = (Path(__file__).resolve().parents[1] / "app" / "app.py").read_text(encoding="utf-8")


class AppPlexApiContractTests(unittest.TestCase):
    def test_runtime_keeps_collectors_and_separates_publication(self):
        self.assertIn("PlexApiRuntime", APP)
        self.assertIn("api_runtime.collect", APP)
        self.assertIn("mqtt.set_plex_api_available", APP)
        self.assertIn("mqtt.set_discovery_payload", APP)
        self.assertIn("collect_raw_processes", APP)
        self.assertIn("PlexPublicationRuntime", APP)
        self.assertIn("publication.publish_snapshot", APP)
        self.assertNotIn("build_state_payload", APP)

    def test_api_payload_is_passed_to_grouped_publication_runtime(self):
        self.assertIn("api_runtime.payload()", APP)
        self.assertIn("publication.publish_snapshot(", APP)


if __name__ == "__main__":
    unittest.main()
