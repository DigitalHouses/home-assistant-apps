"""Installer-added administrator artifacts participate in existing rollback."""
import importlib.machinery
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class ManagementRollbackTests(unittest.TestCase):
    def test_rollback_restores_cli_and_removes_new_reference(self):
        source = Path(__file__).resolve().parents[1] / 'bin/digitalhouses-plex-agent-update-runner'
        loader = importlib.machinery.SourceFileLoader('management_updater_test', str(source))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        updater = importlib.util.module_from_spec(spec)
        loader.exec_module(updater)
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            def local(path):
                return tmp / str(path).lstrip('/')
            runtime = tmp / 'app'
            runtime.mkdir()
            (runtime / 'VERSION').write_text('0.8.6\n')
            cli = local('/usr/local/bin/dh-plex-agent')
            reference = local('/root/dh-plex-agent.txt')
            for path in (cli, local(updater.CONFIG), local(updater.UNIT)):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('original')
            cli.chmod(0o750)
            private = tmp / 'private'
            private.mkdir()
            with patch.multiple(updater, ROOT=runtime, STATE=runtime,
                                CONFIG=local(updater.CONFIG), UNIT=local(updater.UNIT),
                                PRIVATE=private, BACKUP=private / 'update-backup',
                                FILES={key:local(value) for key,value in updater.FILES.items()}), patch.object(updater, 'run'):
                updater.backup_files()
                cli.write_text('replaced')
                reference.parent.mkdir(parents=True, exist_ok=True)
                reference.write_text('new reference')
                updater.rollback(restart=False)
            self.assertEqual(cli.read_text(), 'original')
            self.assertEqual(cli.stat().st_mode & 0o777, 0o750)
            self.assertFalse(reference.exists())
