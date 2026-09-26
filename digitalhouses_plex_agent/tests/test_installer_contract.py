import subprocess
import tempfile
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
        self.assertIn(
            '${LEGACY_TOPIC_PREFIX}([[:space:]]*)\\$#\\\\1${CANONICAL_TOPIC_PREFIX}\\\\2#"',
            INSTALLER,
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            config = Path(tmp_dir) / "plex.conf"
            config.write_text(
                "[mqtt]\n"
                "topic_prefix = DigitalHouses/Global/plex_monitoring\n"
            )
            script = r"""
set -euo pipefail
LEGACY_TOPIC_PREFIX="DigitalHouses/Global/plex_monitoring"
CANONICAL_TOPIC_PREFIX="DigitalHouses/Global/digitalhouses_plex_agent"
CONFIG_FILE="$1"

sed -i -E \
    "s#^([[:space:]]*topic_prefix[[:space:]]*=[[:space:]]*)${LEGACY_TOPIC_PREFIX}([[:space:]]*)\$#\\1${CANONICAL_TOPIC_PREFIX}\\2#" \
    "${CONFIG_FILE}"
"""
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
