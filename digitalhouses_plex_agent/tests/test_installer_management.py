import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ManagementInstallerTests(unittest.TestCase):
    def test_cli_install_is_admin_only(self):
        source = (ROOT / 'install.sh').read_text()
        self.assertIn('"${APP_DIR}/bin/dh-plex-agent"', source)
        self.assertIn('"/usr/local/bin/dh-plex-agent"', source)
        self.assertIn('install -o root -g root -m 0750', source)

    def test_quick_reference_is_compact_and_private(self):
        source = (ROOT / 'install.sh').read_text()
        self.assertIn('cat >"/root/dh-plex-agent.txt"', source)
        body = source.split('cat >"/root/dh-plex-agent.txt"', 1)[1].split('\nDH_PLEX_REFERENCE\n', 1)[0].split('\n', 1)[1]
        self.assertLess(len(body.splitlines()), 16)
        for command in ('status', 'restart', 'help', 'set mqtt_ip=', 'set mqtt_port=', 'set log_level='):
            self.assertIn('/usr/local/bin/dh-plex-agent ' + command, body)
        self.assertIn('cat /etc/digitalhouses_plex_agent/digitalhouses_plex_agent.conf', body)
        self.assertIn('secrets', body)
        self.assertIn('https://github.com/DigitalHouses/home-assistant-apps/tree/main/digitalhouses_plex_agent', body)
        self.assertIn('chmod 0600 "/root/dh-plex-agent.txt"', source)

    def test_unattended_preflights_native_config_before_side_effects(self):
        source = (ROOT / 'install.sh').read_text()
        self.assertIn('PREPARED_CONFIG="${tmp_dir}/native.conf"', source)
        self.assertIn('CONFIG_BASE_SHA="$(sha256sum "${CONFIG_FILE}"', source)
        self.assertIn('PYTHONPATH="${SOURCE_APP}" python3 -m app.install_config', source)
        self.assertIn('--non-interactive', source)
        self.assertIn('--mqtt-password-stdin', source)
        self.assertLess(source.index('PREPARED_CONFIG='), source.index('groupadd --system'))
        self.assertLess(source.index('PREPARED_CONFIG='), source.index('cp -a "${SOURCE_APP}/."'))
        self.assertNotIn('read -r -s mqtt_password', source)
