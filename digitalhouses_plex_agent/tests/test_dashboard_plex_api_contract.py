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


    def test_intel_gpu_diagnostics_use_native_entities_and_report_driver_details(self):
        section = DASHBOARD.split("title: Intel GPU · Диагностика", 1)[1].split(
            "      - type: logbook", 1
        )[0]
        self.assertIn("type: entities", DASHBOARD.split(
            "title: Intel GPU · Диагностика", 1
        )[0][-40:])
        self.assertIn("attribute: pci_address", section)
        self.assertIn("attribute: driver_name", section)
        self.assertIn("attribute: available", section)
        self.assertIn("sensor.dh_plex_agent_gpu_driver_status", section)
        self.assertIn("sensor.dh_plex_agent_gpu_status", section)
        self.assertNotIn("custom:mushroom-template-card", section)


if __name__ == "__main__":
    unittest.main()

