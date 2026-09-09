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

    def test_local_admin_token_is_copied_to_protected_config_file(self):
        self.assertIn('PLEX_LOCAL_ADMIN_TOKEN=', INSTALLER)
        self.assertIn('PLEX_API_TOKEN_FILE="${CONFIG_DIR}/plex_local_admin_token"', INSTALLER)
        self.assertIn('install -o root -g "${SERVICE_GROUP}" -m 0640', INSTALLER)
        self.assertIn('"${PLEX_LOCAL_ADMIN_TOKEN}" "${PLEX_API_TOKEN_FILE}"', INSTALLER)

    def test_installer_removes_legacy_systemd_credential_dropin(self):
        self.assertIn('TOKEN_DROPIN_FILE=', INSTALLER)
        self.assertIn('rm -f "${TOKEN_DROPIN_FILE}"', INSTALLER)
        self.assertNotIn('LoadCredential=', INSTALLER)


if __name__ == "__main__":
    unittest.main()
