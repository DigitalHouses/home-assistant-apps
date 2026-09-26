import subprocess
import tempfile
import textwrap
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


    def test_default_mqtt_topic_migration_sed_executes(self):
        start = INSTALLER.index(
            '        sed -i -E \\\n'
            '            "s#^([[:space:]]*topic_prefix'
        )
        end = INSTALLER.index("\n    fi", start)
        sed_block = textwrap.dedent(INSTALLER[start:end])

        with tempfile.TemporaryDirectory() as tmp_dir:
            config = Path(tmp_dir) / "plex.conf"
            config.write_text(
                "[mqtt]\n"
                "topic_prefix = DigitalHouses/Global/plex_monitoring\n"
            )
            script = (
                "set -euo pipefail\n"
                'LEGACY_TOPIC_PREFIX="DigitalHouses/Global/plex_monitoring"\n'
                'CANONICAL_TOPIC_PREFIX="DigitalHouses/Global/digitalhouses_plex_agent"\n'
                'CONFIG_FILE="$1"\n'
                f"{sed_block}\n"
            )
            result = subprocess.run(
                ["bash", "-c", script, "installer-test", str(config)],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(
                result.returncode,
                0,
                msg=f"stdout={result.stdout}\nstderr={result.stderr}",
            )
            self.assertEqual(
                config.read_text(),
                "[mqtt]\n"
                "topic_prefix = DigitalHouses/Global/digitalhouses_plex_agent\n",
            )

if __name__ == "__main__":
    unittest.main()
