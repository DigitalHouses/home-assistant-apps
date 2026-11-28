from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(not shutil.which("node"), reason="Node.js unavailable")
def test_dashboard_live_refresh():
    subprocess.run(["node", "--test", str(Path(__file__).with_name("dashboard_live.cjs"))], check=True)
