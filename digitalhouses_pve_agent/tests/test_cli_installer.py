import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import install_config
from app.config import load_config

ROOT = Path(__file__).resolve().parents[1]


class InstallerManagementTests(unittest.TestCase):
    def test_unattended_native_prepare_and_missing_host(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config'
            path.write_text('[mqtt]\nhost=\n')
            with self.assertRaises(ValueError):
                install_config.prepare(path, [], non_interactive=True)
            with patch('sys.stdin', io.StringIO('secret\n')):
                install_config.prepare(path, ['mqtt_host=broker', 'mqtt_password=-'], non_interactive=True)
            self.assertEqual(load_config(path).mqtt.password, 'secret')

    def test_noninteractive_rejects_bare_secret_without_prompting(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config'
            path.write_text('[mqtt]\nhost=broker\n')
            with patch('app.cli.getpass.getpass', side_effect=AssertionError('prompt')), patch('sys.stdin.isatty', return_value=True):
                with self.assertRaises(ValueError):
                    install_config.prepare(path, ['mqtt_password'], non_interactive=True)

    def test_existing_config_preserved_and_commit_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config'
            text = '# retained\n[mqtt]\nhost=broker\n\n[unknown]\nfoo=bar\n'
            path.write_text(text)
            path.chmod(0o640)
            install_config.prepare(path, [], non_interactive=True)
            self.assertEqual(path.read_text(), text)
            staged = Path(directory) / 'prepared'
            staged.write_text(text.replace('host=broker', 'host=new'))
            install_config.commit(staged, path)
            self.assertEqual(path.stat().st_mode & 0o777, 0o640)
            self.assertIn('# retained', path.read_text())

    def test_concurrent_native_config_edit_is_not_overwritten(self):
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config'
            path.write_text('[mqtt]\nhost=original\n')
            old_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            staged = Path(directory) / 'prepared'
            staged.write_text('[mqtt]\nhost=new\n')
            path.write_text('[mqtt]\nhost=other-admin\n')
            with self.assertRaisesRegex(ValueError, 'changed during installation'):
                install_config.commit(staged, path, old_hash)
            self.assertIn('other-admin', path.read_text())

    def test_installer_preflight_precedes_service_stop_and_no_old_prompt(self):
        script = (ROOT / 'install.sh').read_text()
        for flag in ('--non-interactive', '--set', '--mqtt-password-stdin', '--ups-command-password-stdin'):
            self.assertIn(flag, script)
        self.assertLess(script.index('-m app.install_config'), script.index('systemctl stop'))
        self.assertIn('bin/dh-pve-agent', script)
        self.assertIn('-m 0750', script)
        self.assertIn('/root/dh-pve-agent.txt', script)
        self.assertNotIn('IFS= read -r -s mqtt_password', script)

    def test_installer_uses_missing_nut_tolerance_only_for_install_preflight(self):
        script = (ROOT / 'install.sh').read_text()
        self.assertEqual(script.count('allow_nut_unavailable=True'), 3)
        cli = (ROOT / 'app/cli.py').read_text()
        self.assertIn('guard_restart(load_config(DEFAULT_CONFIG))', cli)
        self.assertNotIn('allow_nut_unavailable=True', cli)

    def test_guide_and_updater_artifacts(self):
        guide = (ROOT / 'dh-pve-agent.txt').read_text()
        for command in ('status', 'restart', 'help', 'set mqtt_ip='):
            self.assertIn('/usr/local/bin/dh-pve-agent ' + command, guide)
        self.assertIn('secrets', guide)
        updater = (ROOT / 'bin/digitalhouses-pve-agent-update-runner').read_text()
        self.assertIn('"cli":', updater)
        self.assertIn('/root/dh-pve-agent.txt', updater)
        self.assertIn('legacy_guide', updater)


if __name__ == '__main__':
    unittest.main()
