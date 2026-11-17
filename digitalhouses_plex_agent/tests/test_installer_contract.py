import subprocess
import tempfile
import unittest
from pathlib import Path

INSTALLER = (Path(__file__).resolve().parents[1] / "install.sh").read_text()


class InstallerContractTests(unittest.TestCase):
    def test_default_instance_is_native_ini_and_noninteractive(self):
        from app.config import load_config
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "native.conf"
            config.write_text("[mqtt]\nhost = broker.example\n")
            native = load_config(config)
        self.assertEqual(native.general.instance_id, "plex")
        self.assertEqual(native.general.instance_name, "DH Plex")
        self.assertIn("--non-interactive", INSTALLER)
        self.assertIn("--set", INSTALLER)
        self.assertNotIn("Instance ID [plex]", INSTALLER)
        self.assertNotIn("Instance name [DH Plex]", INSTALLER)

    def test_venv_permissions_are_repaired(self):
        self.assertIn('(umask 0077; printf ', INSTALLER)
        self.assertIn(r'[telemetry]\nenabled = true', INSTALLER)
        self.assertIn('install -o root -g root -m 0600 "${PREPARED_CONFIG}" "${CONFIG_FILE}"', INSTALLER)
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
