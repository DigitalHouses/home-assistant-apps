from pathlib import Path
import unittest

INSTALLER = (Path(__file__).resolve().parents[1] / "install.sh").read_text(encoding="utf-8")


class InstallerPlexApiTests(unittest.TestCase):
    def test_first_install_writes_plex_api_defaults_without_token(self):
        self.assertIn('"[plex_api]"', INSTALLER)
        self.assertIn('"enabled = true"', INSTALLER)
        self.assertIn('"base_url = http://127.0.0.1:32400"', INSTALLER)
        self.assertIn('"library_refresh_seconds = 3600"', INSTALLER)
        self.assertNotIn('token = ', INSTALLER)

    def test_local_admin_token_is_loaded_as_systemd_credential(self):
        self.assertIn('PLEX_LOCAL_ADMIN_TOKEN=', INSTALLER)
        self.assertIn('plex-local-token.conf', INSTALLER)
        self.assertIn('LoadCredential=', INSTALLER)
        self.assertIn('plex_local_admin_token:', INSTALLER)


if __name__ == "__main__":
    unittest.main()
