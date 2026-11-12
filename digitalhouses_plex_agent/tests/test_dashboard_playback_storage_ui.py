"""Lovelace UI must not confuse lingering transcoder processes with playback."""
from pathlib import Path
import unittest

DASHBOARD = (
    Path(__file__).resolve().parents[1]
    / "examples" / "lovelace" / "plex-dashboard.yaml"
).read_text(encoding="utf-8")


class PlaybackAndStorageDashboardTests(unittest.TestCase):
    def test_plex_work_uses_api_playback_not_linux_transcoder_process(self):
        card = DASHBOARD.split("        primary: Работа Plex\n", 1)[1].split(
            "      - type: custom:mushroom-template-card", 1
        )[0]
        self.assertIn("entity: binary_sensor.dh_plex_agent_playback_active", DASHBOARD)
        self.assertIn("playing and transcode", card)
        self.assertIn("binary_sensor.dh_plex_agent_video_transcoding_active", card)
        self.assertIn("binary_sensor.dh_plex_agent_audio_transcoding_active", card)
        self.assertIn("binary_sensor.dh_plex_agent_audio_analysis_running", card)
        self.assertIn("sensor.dh_plex_agent_background_processes", card)
        self.assertIn("Ожидание", card)
        self.assertNotIn("sensor.dh_plex_agent_activity", card)
        self.assertNotIn("binary_sensor.dh_plex_agent_transcoder_running", card)

    def test_storage_progress_bars_below_full_width_text(self):
        section = DASHBOARD.split("'plex_section') == 'library_storage'", 1)[1].split(
            "      - type: custom:auto-entities", 1
        )[0]
        self.assertIn("'bar_position': 'below'", section)
        self.assertIn("'secondary': 'Свободно '", section)
        self.assertIn("'bar_size': 'medium'", section)
        self.assertIn("'storage_display_name'", section)


if __name__ == "__main__":
    unittest.main()
