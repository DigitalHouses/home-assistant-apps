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

    def test_unattended_requires_native_config_before_side_effects(self):
        source = (ROOT / 'install.sh').read_text()
        block = source.split('# Native configuration preflight', 1)[1].split('need_apt=0', 1)[0]
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'config'
            legacy = Path(tmp) / 'legacy'
            script = 'CONFIG_FILE="$1"\nLEGACY_CONFIG_FILE="$2"\n' + block
            absent = subprocess.run(['bash', '-c', script, 'test', str(config), str(legacy)], capture_output=True, text=True, start_new_session=True)
            self.assertNotEqual(absent.returncode, 0)
            self.assertIn('native INI', absent.stdout)
            self.assertFalse(config.exists())
            content = '[mqtt]\nhost = broker.example\n# preserved\n'
            config.write_text(content)
            configured = subprocess.run(['bash', '-c', script, 'test', str(config), str(legacy)], capture_output=True, text=True, start_new_session=True)
            self.assertEqual(configured.returncode, 0, configured.stderr)
            self.assertEqual(config.read_text(), content)
