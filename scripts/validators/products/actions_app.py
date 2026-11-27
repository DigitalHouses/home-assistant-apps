"""Contract checks for the experimental, release-managed Actions App."""

from pathlib import Path
from typing import Any

from validators.common import fail, require_files


def validate_actions(root: Path, app: Path, context: dict[str, Any]) -> None:
    require_files(root, [app / "rootfs/app/app.py", app / "tests/test_scaffold.py"])
    config = context["config"]
    if config.get("stage") != "experimental":
        fail("Actions App must stay experimental until accepted")
    if config.get("boot") != "manual":
        fail("Actions App must not boot automatically")
    if config.get("image") != "ghcr.io/digitalhouses/digitalhouses_actions_app":
        fail("Actions App must use canonical immutable GHCR repository")
