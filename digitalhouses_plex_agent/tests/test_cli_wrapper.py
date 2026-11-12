import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class CliWrapperTests(unittest.TestCase):
    def test_absolute_runtime_and_any_cwd_ignores_callers_pythonpath(self):
        source = (Path(__file__).resolve().parents[1] / 'bin/dh-plex-agent').read_text()
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            install = tmp / 'installed'
            (install / 'app').mkdir(parents=True)
            (install / '.venv/bin').mkdir(parents=True)
            (install / 'app/__init__.py').touch()
            (install / 'app/cli.py').write_text('import os, sys; print("installed", os.getcwd(), sys.argv[1:])\n')
            python = install / '.venv/bin/python'
            python.symlink_to('/usr/bin/python3')
            wrapper = tmp / 'dh-plex-agent'
            wrapper.write_text(source.replace('/opt/digitalhouses/digitalhouses_plex_agent', str(install)))
            wrapper.chmod(0o750)
            outsider = tmp / 'outsider'
            (outsider / 'app').mkdir(parents=True)
            (outsider / 'app/__init__.py').touch()
            (outsider / 'app/cli.py').write_text('raise RuntimeError("untrusted cwd module")')
            result = subprocess.run([str(wrapper), 'help'], cwd=outsider, env=dict(os.environ, PYTHONPATH=str(outsider)), text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('installed ' + str(install), result.stdout)
            self.assertIn("['help']", result.stdout)
            (install / 'app/cli.py').unlink()
            result = subprocess.run([str(wrapper), 'status'], cwd=outsider, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('ERROR', result.stdout + result.stderr)
