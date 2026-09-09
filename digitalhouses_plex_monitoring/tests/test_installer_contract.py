import unittest
from pathlib import Path

INSTALLER = (Path(__file__).resolve().parents[1] / "install.sh").read_text()

class InstallerContractTests(unittest.TestCase):
    def test_default_instance_is_noninteractive(self):
        self.assertIn('instance_id="${DIGITALHOUSES_INSTANCE_ID:-plex}"', INSTALLER)
        self.assertIn('instance_name="${DIGITALHOUSES_INSTANCE_NAME:-$(hostname -s)}"', INSTALLER)
        self.assertNotIn("Instance ID [plex]", INSTALLER)
        self.assertNotIn("Instance name [DH Plex]", INSTALLER)

    def test_venv_permissions_are_repaired(self):
        self.assertIn('previous_umask="$(umask)"', INSTALLER)
        self.assertIn('umask "${previous_umask}"', INSTALLER)
        self.assertIn('chmod -R a+rX "${APP_DIR}/.venv"', INSTALLER)

if __name__ == "__main__":
    unittest.main()
