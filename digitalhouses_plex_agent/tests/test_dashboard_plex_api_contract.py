from pathlib import Path
import unittest

DASHBOARD = (
    Path(__file__).resolve().parents[1]
    / "examples"
    / "lovelace"
    / "plex-dashboard.yaml"
).read_text(encoding="utf-8")


class DashboardPlexApiContractTests(unittest.TestCase):
    def test_live_dashboard_uses_canonical_plex_agent_entities(self):
        self.assertNotIn("sensor.plex_vm", DASHBOARD)
        self.assertNotIn("update.plex_vm", DASHBOARD)
        self.assertIn("binary_sensor.dh_plex_agent_playback_active", DASHBOARD)
        self.assertIn("sensor.dh_plex_agent_playback_started_at", DASHBOARD)
        self.assertIn("sensor.dh_plex_agent_playback_sessions", DASHBOARD)
        self.assertIn("sensor.dh_plex_agent_library_*", DASHBOARD)

    def test_live_dashboard_handles_audio_and_video_session_details(self):
        self.assertIn("s.get('content_type') == 'audio'", DASHBOARD)
        self.assertIn("s.get('media_type') == 'episode'", DASHBOARD)
        self.assertIn("s.get('audio_codec')", DASHBOARD)
        self.assertIn("s.get('video_codec')", DASHBOARD)


if __name__ == "__main__":
    unittest.main()
