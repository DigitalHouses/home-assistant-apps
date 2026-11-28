"""Run the canonical DH Journal contract through existing repository CI."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]

class SharedJournalContract(unittest.TestCase):
    def test_generated_snapshots(self):
        subprocess.run([sys.executable, "scripts/vendor_dh_journal.py", "--check"], cwd=ROOT, check=True)

    def test_canonical_library(self):
        env = dict(os.environ, PYTHONPATH=str(ROOT / "shared/dh_journal"))
        subprocess.run([sys.executable, "-m", "unittest", "discover", "-s",
                        "shared/dh_journal/tests", "-v"], cwd=ROOT, env=env, check=True)

    @unittest.skipUnless(shutil.which("node"), "Node.js not installed")
    def test_browser_script(self):
        subprocess.run(["node", "--check", "shared/dh_journal/dh_journal/web/journal.js"], cwd=ROOT, check=True)
