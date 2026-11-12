"""Lovelace UI must not confuse lingering transcoder processes with playback."""
from pathlib import Path
import unittest

DASHBOARD = (
    Path(__file__).resolve().parents[1]
    / "examples" / "lovelace" / "plex-dashboard.yaml"
).read_text(encoding="utf-8")


class PlaybackAndStorageDashboardTests(unittest.TestCase):
    def test_plex_work_reports_full_width_playback_mode(self):
        card = DASHBOARD.split("        primary: Работа Plex\n", 1)[1].split(
            "      - type: grid\n        columns: 2", 1
        )[0]
        self.assertIn("entity: binary_sensor.dh_plex_agent_playback_active", DASHBOARD)
        self.assertIn("elif playing", card)
        self.assertIn("Воспроизведение", card)
        self.assertIn("state_attr('sensor.dh_plex_agent_playback_sessions', 'sessions')", card)
        self.assertIn("'Transcoding' if raw == 'Transcode' else raw", card)
        self.assertIn("ns.modes | join(' · ')", card)
        self.assertIn("grid_options:\n          columns: 12\n          rows: 1", card)
        self.assertIn("binary_sensor.dh_plex_agent_audio_analysis_running", card)
        self.assertIn("sensor.dh_plex_agent_background_processes", card)
        self.assertIn("Ожидание", card)
        self.assertNotIn("binary_sensor.dh_plex_agent_transcoder_running", card)
        self.assertNotIn("sensor.dh_plex_agent_activity", card)

    def test_two_independent_transcoding_cards(self):
        section = DASHBOARD.split("      - type: grid\n        columns: 2", 1)[1].split(
            "      - type: custom:mushroom-template-card\n        entity: button.dh_plex_agent_refresh", 1
        )[0]
        self.assertIn("square: false", section)
        self.assertEqual(section.count("type: custom:mushroom-template-card"), 2)
        self.assertIn("primary: Video Transcoding", section)
        self.assertIn("primary: Audio Transcoding", section)
        self.assertIn("entity: binary_sensor.dh_plex_agent_video_transcoding_active", section)
        self.assertIn("entity: binary_sensor.dh_plex_agent_audio_transcoding_active", section)
        self.assertEqual(section.count("Active"), 2)
        self.assertEqual(section.count("Idle"), 2)
        self.assertEqual(section.count("Недоступно"), 2)
        self.assertNotIn("sensor.dh_plex_agent_activity", section)
        self.assertNotIn("binary_sensor.dh_plex_agent_transcoder_running", section)

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
