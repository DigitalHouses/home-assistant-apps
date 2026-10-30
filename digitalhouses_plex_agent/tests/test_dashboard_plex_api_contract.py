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


    def test_gpu_diagnostics_use_approved_mushroom_templates(self):
        section = DASHBOARD.split("primary: Intel GPU · Драйвер", 1)[1].split(
            "      - type: logbook", 1
        )[0]
        # Two independent Mushroom cards retain Plex Agent's canonical
        # stream of truth: bound kernel driver != operational GPU.
        self.assertEqual(section.count("type: custom:mushroom-template-card"), 1)
        self.assertIn("primary: Intel GPU · Работа", section)
        self.assertIn("entity: sensor.dh_plex_agent_gpu_status", section)
        self.assertIn("driver_name", section)
        self.assertIn("pci_address", section)
        self.assertIn("state_attr(entity, 'available')", section)
        self.assertIn("status == 'bound'", section)
        self.assertIn("status == 'ok'", section)
        self.assertIn("status in ['error', 'helper_error']", section)
        self.assertIn("multiline_secondary: true", section)
        self.assertNotIn("type: attribute", section)
        self.assertNotIn("type: entities", section)
        self.assertIn(
            "type: custom:mushroom-template-card\n"
            "            entity: sensor.dh_plex_agent_gpu_driver_status",
            DASHBOARD,
        )


if __name__ == "__main__":
    unittest.main()

