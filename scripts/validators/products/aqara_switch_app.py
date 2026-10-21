"""Contract checks for the inert Aqara Switch App scaffold."""

from pathlib import Path
from typing import Any

from validators.common import fail, require_files


def validate_aqara_switch(root: Path, app: Path, context: dict[str, Any]) -> None:
    require_files(root, [app / "rootfs/app/app.py", app / "tests/test_scaffold.py"])
    config = context["config"]
    if config.get("stage") != "experimental":
        fail("Aqara Switch App scaffold must stay experimental")
    if config.get("boot") != "manual":
        fail("Aqara Switch App scaffold must not boot automatically")
    if config.get("image"):
        fail("Aqara Switch App scaffold must not claim a published image")
