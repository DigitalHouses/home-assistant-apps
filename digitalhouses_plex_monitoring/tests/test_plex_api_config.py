import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import load_config


class PlexApiConfigTests(unittest.TestCase):
    def _config(self, extra=""):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "app.conf"
        path.write_text("[mqtt]\nhost = mqtt\n" + extra, encoding="utf-8")
        return load_config(path)

    def test_plex_api_defaults(self):
        config = self._config()
        self.assertTrue(config.plex_api.enabled)
        self.assertEqual(config.plex_api.base_url, "http://127.0.0.1:32400")
        self.assertTrue(str(config.plex_api.token_file).endswith(".LocalAdminToken"))
        self.assertEqual(config.plex_api.timeout_seconds, 3.0)
        self.assertEqual(config.plex_api.library_refresh_seconds, 3600.0)


if __name__ == "__main__":
    unittest.main()
