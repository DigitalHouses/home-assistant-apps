import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import load_config
from app.discovery import build_discovery_payload, build_topics
from app.models import BuildInfo
from app.plex_api import LibraryInfo


class PlexApiDiscoveryTests(unittest.TestCase):
    def config(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "app.conf"
        path.write_text("[mqtt]\nhost = mqtt\n", encoding="utf-8")
        return load_config(path)

    def test_api_availability_topic(self):
        topics = build_topics(self.config())
        self.assertEqual(
            topics.plex_api_availability,
            "DigitalHouses/Global/plex_monitoring/plex_api_availability",
        )

    def test_playback_entities_use_api_availability(self):
        config = self.config()
        payload = build_discovery_payload(config, BuildInfo("0.2.0", "main", "abcdef"))
        components = payload["components"]
        expected = {
            "playback_count": "sensor.dh_plex_playback_count",
            "playback_sessions": "sensor.dh_plex_playback_sessions",
            "playback_active": "binary_sensor.dh_plex_playback_active",
            "video_playback_active": "binary_sensor.dh_plex_video_playback_active",
            "audio_playback_active": "binary_sensor.dh_plex_audio_playback_active",
            "api_status": "sensor.dh_plex_api_status",
            "libraries": "sensor.dh_plex_libraries",
        }
        for component, entity_id in expected.items():
            self.assertEqual(components[component]["default_entity_id"], entity_id)
        api_topic = build_topics(config).plex_api_availability
        playback_topics = [item["topic"] for item in components["playback_count"]["availability"]]
        self.assertIn(api_topic, playback_topics)
        status_topics = [item["topic"] for item in components["api_status"]["availability"]]
        self.assertNotIn(api_topic, status_topics)

    def test_dynamic_library_entity_uses_section_id(self):
        libraries = (
            LibraryInfo("1", "Фильмы", "movie", "video", 15, "/movies", movies=15),
            LibraryInfo("3", "Музыка", "artist", "audio", 160, "/music", artists=3, albums=20, tracks=160),
        )
        payload = build_discovery_payload(
            self.config(), BuildInfo("0.2.0", "main", "abcdef"), libraries
        )
        components = payload["components"]
        self.assertEqual(
            components["library_1"]["default_entity_id"],
            "sensor.dh_plex_library_1",
        )
        self.assertEqual(
            components["library_3"]["default_entity_id"],
            "sensor.dh_plex_library_3",
        )
        self.assertIn("libraries_by_id", components["library_1"]["value_template"])
        self.assertIn("item_count", components["library_1"]["value_template"])


if __name__ == "__main__":
    unittest.main()
