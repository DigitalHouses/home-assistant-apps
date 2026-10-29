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


if __name__ == "__main__":
    unittest.main()
