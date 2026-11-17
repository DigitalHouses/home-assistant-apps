"""Unattended Plex Agent installation uses the same native INI as CLI set."""
from __future__ import annotations

import hashlib
from io import StringIO
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.cli import CliError, set_config
from app.config import load_config
from app.install_config import commit, prepare, main


ROOT = Path(__file__).resolve().parents[1]


class UnattendedInstallTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conf = Path(self.tmp.name) / "native.ini"
        self.conf.write_text(
            "# Existing operator comment\n[general]\ninstance_id = plex\n"
            "[mqtt]\nhost = \nport = 1883\n",
            encoding="utf-8",
        )

    def test_first_install_an_ansible_batch_requires_no_tty_or_service(self) -> None:
        with patch("app.cli.service_info", side_effect=AssertionError("must not consult systemd")):
            prepare(self.conf, ["mqtt_ip=192.0.2.24", "mqtt_port=1884",
                                "log_level=info"], non_interactive=True)
        config = load_config(self.conf)
        self.assertEqual(config.mqtt.host, "192.0.2.24")
        self.assertEqual(config.mqtt.port, 1884)
        self.assertIn("# Existing operator comment", self.conf.read_text())
        initial = self.conf.read_bytes()
        with patch("app.cli.service_info", side_effect=AssertionError("must not consult systemd")):
            prepare(self.conf, ["mqtt_ip=192.0.2.24", "mqtt_port=1884"],
                    non_interactive=True)
        self.assertEqual(self.conf.read_bytes(), initial)

    def test_first_install_invalid_and_missing_host_leave_file_unchanged(self) -> None:
        original = self.conf.read_bytes()
        with self.assertRaises(CliError):
            prepare(self.conf, [], non_interactive=True)
        self.assertEqual(self.conf.read_bytes(), original)
        with self.assertRaises(Exception):
            prepare(self.conf, ["mqtt_ip=192.0.2.24", "mqtt_port=99999"],
                    non_interactive=True)
        self.assertEqual(self.conf.read_bytes(), original)

    def test_secret_comes_only_from_stdin_no_restart(self) -> None:
        with patch("sys.stdin", StringIO("do-not-print-me\n")), \
             patch("app.cli.service_info", side_effect=AssertionError("no systemd")):
            prepare(self.conf, ["mqtt_ip=broker.local", "mqtt_password=-"],
                    non_interactive=True)
        self.assertEqual(load_config(self.conf).mqtt.password, "do-not-print-me")
        self.assertIn("password = do-not-print-me", self.conf.read_text())

    def test_literal_secret_argument_is_rejected(self) -> None:
        original = self.conf.read_bytes()
        with self.assertRaises(CliError):
            prepare(self.conf, ["mqtt_ip=broker.local", "mqtt_password=plaintext"],
                    non_interactive=True)
        self.assertEqual(self.conf.read_bytes(), original)

    def test_commit_preserves_existing_mode_checks_sha_and_is_idempotent(self) -> None:
        target = Path(self.tmp.name) / "installed.conf"
        target.write_text("# existing\n[mqtt]\nhost = broker.local\n")
        target.chmod(0o640)
        expected = hashlib.sha256(target.read_bytes()).hexdigest()
        prepared = Path(self.tmp.name) / "prepared.ini"
        prepared.write_text("[mqtt]\nhost = broker-new.local\n")
        commit(prepared, target, expected)
        self.assertEqual(load_config(target).mqtt.host, "broker-new.local")
        self.assertEqual(target.stat().st_mode & 0o777, 0o640)
        inode = target.stat().st_ino
        commit(prepared, target, hashlib.sha256(target.read_bytes()).hexdigest())
        self.assertEqual(target.stat().st_ino, inode)
        with self.assertRaises(CliError):
            commit(prepared, target, expected)
        self.assertEqual(target.read_bytes(), prepared.read_bytes())

    def test_plain_install_prompts_on_controlling_terminal(self) -> None:
        # Source downloaded with curl | bash uses stdin; prompts use /dev/tty.
        import builtins
        native_open = builtins.open
        class DuplexTTY:
            def __init__(self) -> None:
                self.answers = StringIO("broker.local\n\noperator\ny\n")
                self.prompts: list[str] = []
                self.closed = False
            def __enter__(self):
                return self
            def __exit__(self, *_args):
                self.closed = True
            def write(self, value: str) -> None:
                self.prompts.append(value)
            def flush(self) -> None:
                pass
            def readline(self) -> str:
                return self.answers.readline()
        tty = DuplexTTY()
        def tty_open(path, *args, **kwargs):
            if str(path) == "/dev/tty":
                return tty
            return native_open(path, *args, **kwargs)
        with patch("builtins.open", side_effect=tty_open) as opened, \
             patch("app.install_config.getpass.getpass", return_value="secret-value") as getpass:
            prepare(self.conf, [], non_interactive=False)
        cfg = load_config(self.conf)
        self.assertEqual((cfg.mqtt.host, cfg.mqtt.port, cfg.mqtt.username),
                         ("broker.local", 1883, "operator"))
        self.assertEqual(cfg.mqtt.password, "secret-value")
        self.assertTrue(any(call.args[0] == "/dev/tty" for call in opened.call_args_list))
        getpass.assert_called_once()
        self.assertTrue(tty.closed)
        self.assertIn("Confirm MQTT settings", "".join(tty.prompts))

    def test_any_cli_setting_never_prompts_even_with_missing_host(self) -> None:
        import builtins
        native_open = builtins.open
        def fail_tty_only(path, *args, **kwargs):
            if str(path) == "/dev/tty":
                raise AssertionError("must not open /dev/tty")
            return native_open(path, *args, **kwargs)
        with patch("builtins.open", side_effect=fail_tty_only):
            with self.assertRaisesRegex(CliError, "mqtt.host is required"):
                prepare(self.conf, ["mqtt_port=1884"], non_interactive=False)
            prepare(self.conf, ["mqtt_ip=192.0.2.25", "mqtt_port=1884"],
                    non_interactive=False)
        self.assertEqual(load_config(self.conf).mqtt.host, "192.0.2.25")
        self.assertEqual(load_config(self.conf).mqtt.port, 1884)

    def test_plain_install_without_terminal_explains_mode(self) -> None:
        import builtins
        native_open = builtins.open
        def missing_tty(path, *args, **kwargs):
            if str(path) == "/dev/tty":
                raise OSError("no controlling terminal")
            return native_open(path, *args, **kwargs)
        with patch("builtins.open", side_effect=missing_tty):
            with self.assertRaisesRegex(CliError, "interactive MQTT setup requires a terminal"):
                prepare(self.conf, [], non_interactive=False)

    def test_invalid_configuration_error_redacts_raw_values(self) -> None:
        self.conf.write_text("[mqtt]\nhost = broker.local\nport = 654321\n")
        with patch("sys.argv", ["install_config", str(self.conf)]), \
             patch("app.install_config.os.geteuid", return_value=0):
            stream = io.StringIO()
            with contextlib.redirect_stderr(stream):
                result = main()
        self.assertEqual(result, 1)
        self.assertIn("mqtt.port", stream.getvalue())
        self.assertNotIn("654321", stream.getvalue())

    def test_installer_stages_config_before_mutating_services(self) -> None:
        script = (ROOT / "install.sh").read_text()
        self.assertIn("--non-interactive", script)
        self.assertIn("--mqtt-password-stdin", script)
        self.assertIn('CONFIG_SETTINGS+=("$2"); NON_INTERACTIVE=1', script)
        self.assertIn('CONFIG_SETTINGS+=("mqtt_password=-"); NON_INTERACTIVE=1', script)
        self.assertIn("python3 -m app.install_config", script)
        self.assertLess(script.index('PREPARED_CONFIG='), script.index('groupadd --system'))
        self.assertLess(script.index('PREPARED_CONFIG='), script.index('cp -a "${SOURCE_APP}/."'))
        self.assertIn('CONFIG_BASE_SHA="$(sha256sum', script)
        self.assertNotIn('read -r -s mqtt_password', script)
        bootstrap = (ROOT / "install-latest.sh").read_text()
        self.assertIn('bash "${installer}" "$@"', bootstrap)


if __name__ == "__main__":
    unittest.main()
