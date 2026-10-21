"""Contract checks for the experimental, release-managed Aqara App."""

from pathlib import Path
from typing import Any

from validators.common import fail, require_files


def validate_aqara_switch(root: Path, app: Path, context: dict[str, Any]) -> None:
    require_files(root, [app / "rootfs/app/app.py", app / "tests/test_scaffold.py"])
    config = context["config"]
    if config.get("stage") != "experimental":
        fail("Aqara Switch App must stay experimental until accepted")
    if config.get("boot") != "manual":
        fail("Aqara Switch App must not boot automatically")
    if config.get("image") != "ghcr.io/digitalhouses/digitalhouses_aqara_switch_app":
        fail("Aqara Switch App must use canonical immutable GHCR repository")
