from __future__ import annotations

from pathlib import Path
from typing import Any

from validators.common import fail, require_directories, require_files


def validate_linux_agent(root: Path, app: Path) -> dict[str, Any]:
    require_files(
        root,
        [
            app / "VERSION",
            app / "install.sh",
        ],
    )
    require_directories(
        root,
        [
            app / "app",
            app / "systemd",
        ],
    )

    if not list((app / "app").rglob("*.py")):
        fail(f"{app.name}/app must contain Python source")

    service_files = list((app / "systemd").glob("*.service"))
    if not service_files:
        fail(f"{app.name}/systemd must contain at least one .service unit")

    version = (app / "VERSION").read_text(encoding="utf-8").strip()
    if not version or "\n" in version:
        fail(f"{app.name}/VERSION must contain exactly one non-empty version line")

    changelog = (app / "CHANGELOG.md").read_text(encoding="utf-8")
    if f"## {version}" not in changelog:
        fail(f"{app.name}: CHANGELOG has no {version} section")

    return {
        "type": "linux_agent",
        "version": version,
    }
