"""Verify pinned journal snapshots and the canonical external library in CI."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "digitalhouses_system_globals_app/dh-lib-journal.lock.json"
PACKAGE = LOCK.parent / "rootfs/app/dh_lib_journal"

class SharedJournalContract(unittest.TestCase):
    def test_generated_snapshots(self):
        subprocess.run([sys.executable, "scripts/vendor_dh_journal.py", "--check"], cwd=ROOT, check=True)

    def test_canonical_library(self):
        lock = json.loads(LOCK.read_text())
        with tempfile.TemporaryDirectory() as tmp:
            source = os.environ.get("DH_LIB_JOURNAL_SOURCE")
            if source:
                checkout = Path(source).resolve()
            else:
                checkout = Path(tmp) / "libs"
                subprocess.run(["git", "clone", "--depth", "1", "--branch", lock["tag"],
                                lock["repository"] + ".git", str(checkout)], check=True)
            subprocess.run([sys.executable, "scripts/vendor_dh_journal.py", "--check",
                            "--globals-source", str(checkout)], cwd=ROOT, check=True)
            env = dict(os.environ, PYTHONPATH=str(checkout / "dh_lib_journal"))
            subprocess.run([sys.executable, "-m", "unittest", "discover", "-s",
                            str(checkout / "dh_lib_journal/tests"), "-v"], cwd=ROOT, env=env, check=True)

    @unittest.skipUnless(shutil.which("node"), "Node.js not installed")
    def test_browser_script(self):
        for script in (PACKAGE / "web").glob("*.js"):
            subprocess.run(["node", "--check", str(script)], cwd=ROOT, check=True)
