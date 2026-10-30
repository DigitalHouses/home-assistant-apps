from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = (
    ROOT / "examples" / "packages" / "dh_plex_agent_recorder_package.yaml"
).read_text(encoding="utf-8")


class TranscodingRecorderContractTests(unittest.TestCase):
    def test_recorder_only_keeps_binary_flags(self):
        included, excluded = PACKAGE.split("    exclude:\n", 1)
        for stream in ("video", "audio"):
            binary = f"binary_sensor.dh_plex_agent_{stream}_transcoding_active"
            rich = f"sensor.dh_plex_agent_{stream}_transcoding"
            self.assertIn(f"- {binary}", included)
            self.assertNotIn(f"- {rich}", included)
            self.assertIn(f"- {rich}", excluded)
            self.assertNotIn(f"- {binary}", excluded)



class CanonicalPlexPackageTests(unittest.TestCase):
    def test_legacy_package_replacement_has_current_and_only_current_entity_ids(self):
        package = (
            ROOT / "examples" / "packages" / "dh_plex_app_package.yaml"
        ).read_text(encoding="utf-8")
        self.assertIn("dh_app_plex_monitoring_package:", package)
        include, exclude = package.split("    exclude:\n", 1)
        import re
        included = re.findall(r"^\s*- ((?:sensor|binary_sensor|event)\.[a-z0-9_]+)$", include, re.M)
        excluded = re.findall(r"^\s*- ((?:sensor|binary_sensor|event)\.[a-z0-9_]+)$", exclude, re.M)
        self.assertEqual(len(included), len(set(included)))
        self.assertEqual(len(excluded), len(set(excluded)))
        self.assertFalse(set(included) & set(excluded))
        self.assertTrue(all("_dh_plex_agent_" in entity for entity in included))
        self.assertTrue(all("_dh_plex_agent_" in entity for entity in excluded))
        for kind in ("video", "audio"):
            self.assertIn(f"binary_sensor.dh_plex_agent_{kind}_transcoding_active", included)
            self.assertIn(f"sensor.dh_plex_agent_{kind}_transcoding", excluded)
        for entity in (
            "sensor.dh_plex_agent_cpu",
            "sensor.dh_plex_agent_scanner_cpu",
            "sensor.dh_plex_agent_transcoder_cpu",
            "sensor.dh_plex_agent_gpu_render",
            "sensor.dh_plex_agent_gpu_video",
            "sensor.dh_plex_agent_gpu_video_enhance",
        ):
            self.assertIn(entity, included)
        self.assertIn("sensor.dh_plex_agent_playback_sessions", excluded)
        self.assertIn("event.dh_plex_agent_gpu_diagnostic", excluded)
        self.assertNotIn("event.dh_plex_agent_gpu_diagnostic", included)
        self.assertNotIn("sensor.dh_plex_agent_cpu_avg", package)
        self.assertNotIn("sensor.dh_plex_agent_cpu_max", package)

    def test_package_entity_ids_are_in_canonical_mqtt_discovery(self):
        from tempfile import TemporaryDirectory
        from app.config import load_config
        from app.discovery import build_discovery_payload
        from app.models import BuildInfo
        import re
        package = (
            ROOT / "examples" / "packages" / "dh_plex_app_package.yaml"
        ).read_text(encoding="utf-8")
        entity_ids = set(re.findall(
            r"^\s*- ((?:sensor|binary_sensor|event)\.[a-z0-9_]+)$",
            package, re.M,
        ))
        with TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "plex.conf"
            config_path.write_text("[mqtt]\nhost = mqtt\n", encoding="utf-8")
            components = build_discovery_payload(
                load_config(config_path), BuildInfo("0.8.5", "test", "abcdef")
            )["components"]
        known = {x["default_entity_id"] for x in components.values()
                 if "default_entity_id" in x}
        self.assertEqual(entity_ids - known, set(),
                         "Recorder package references nonexistent entity IDs")


if __name__ == "__main__":
    unittest.main()
