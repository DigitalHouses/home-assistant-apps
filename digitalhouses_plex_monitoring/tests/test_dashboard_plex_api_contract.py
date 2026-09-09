from pathlib import Path
import unittest

DASHBOARD = (
    Path(__file__).resolve().parents[1]
    / "examples"
    / "lovelace"
    / "plex-dashboard.yaml"
).read_text(encoding="utf-8")


class DashboardPlexApiContractTests(unittest.TestCase):
    def test_dashboard_no_longer_depends_on_native_plex_integration(self):
        self.assertNotIn("sensor.plex_vm", DASHBOARD)
        self.assertNotIn("update.plex_vm", DASHBOARD)
        self.assertIn("sensor.dh_plex_playback_count", DASHBOARD)
        self.assertIn("sensor.dh_plex_playback_sessions", DASHBOARD)
        self.assertIn("sensor.dh_plex_library_*", DASHBOARD)

    def test_dashboard_exposes_video_and_audio_playback(self):
        self.assertIn("binary_sensor.dh_plex_video_playback_active", DASHBOARD)
        self.assertIn("binary_sensor.dh_plex_audio_playback_active", DASHBOARD)


if __name__ == "__main__":
    unittest.main()
