import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from validators.apps.plex_monitoring import validate_plex_monitoring
from validators.common import parse_application_metadata, validate_common
from validators.types.linux_agent import validate_linux_agent


class PlexMonitoringValidatorTests(unittest.TestCase):
    def test_current_plex_monitoring_contract(self):
        app = ROOT / "digitalhouses_plex_monitoring"
        metadata = parse_application_metadata(app / "digitalhouses.app")
        validate_common(ROOT, app, metadata)
        context = validate_linux_agent(ROOT, app)
        validate_plex_monitoring(ROOT, app, context)
        expected_version = (app / "VERSION").read_text(encoding="utf-8").strip()
        self.assertEqual(context["version"], expected_version)


if __name__ == "__main__":
    unittest.main()
