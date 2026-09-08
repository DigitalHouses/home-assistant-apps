from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from validators.common import (
    fail,
    load_yaml,
    require_directories,
    require_files,
)

_BUILD_VERSION_RE = re.compile(
    r'^\s*ARG\s+BUILD_VERSION\s*=\s*["\']?([^"\'\s]+)["\']?\s*$',
    re.MULTILINE,
)


def dockerfile_default_version(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    match = _BUILD_VERSION_RE.search(text)
    if not match:
        fail(f"{path}: missing default ARG BUILD_VERSION")
    return match.group(1)


def validate_haos_addon(root: Path, app: Path) -> dict[str, Any]:
    require_files(
        root,
        [
            app / "config.yaml",
            app / "Dockerfile",
            app / "DOCS.md",
            app / "rootfs/run.sh",
            app / "translations/en.yaml",
            app / "translations/ru.yaml",
        ],
    )
    require_directories(
        root,
        [
            app / "rootfs/app",
            app / "translations",
            app / "images",
        ],
    )

    python_sources = list((app / "rootfs/app").rglob("*.py"))
    if not python_sources:
        fail(f"{app.name}/rootfs/app must contain Python source")

    config = load_yaml(app / "config.yaml", root)
    if not isinstance(config, dict):
        fail(f"{app.name}/config.yaml must be a YAML mapping")

    slug = config.get("slug")
    if slug != app.name:
        fail(f"{app.name}: config slug must equal directory name, got {slug!r}")

    version = str(config.get("version") or "").strip()
    if not version:
        fail(f"{app.name}: config version is missing")

    arch = config.get("arch")
    if not isinstance(arch, list) or not arch or not all(
        isinstance(item, str) and item.strip() for item in arch
    ):
        fail(f"{app.name}: arch must be a non-empty list of strings")

    docker_version = dockerfile_default_version(app / "Dockerfile")
    if docker_version != version:
        fail(
            f"{app.name}: Dockerfile BUILD_VERSION {docker_version!r} "
            f"does not match config version {version!r}"
        )

    changelog = (app / "CHANGELOG.md").read_text(encoding="utf-8")
    if f"## {version}" not in changelog:
        fail(f"{app.name}: CHANGELOG has no {version} section")

    for translation in (
        app / "translations/en.yaml",
        app / "translations/ru.yaml",
    ):
        parsed = load_yaml(translation, root)
        if not isinstance(parsed, dict):
            fail(f"{translation.relative_to(root)} must be a YAML mapping")

    return {
        "type": "haos_addon",
        "version": version,
        "config": config,
    }
