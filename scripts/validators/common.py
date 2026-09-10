from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

SUPPORTED_APP_TYPES = {"haos_addon", "linux_agent"}
COMPACT_APPLICATION_NAMES = {"dh_pve_app"}


class ValidationError(RuntimeError):
    pass


def fail(message: str) -> None:
    raise ValidationError(message)


def relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def require_files(root: Path, paths: list[Path]) -> None:
    missing = [path for path in paths if not path.is_file()]
    if missing:
        fail(
            "Missing required files: "
            + ", ".join(relative(path, root) for path in missing)
        )


def require_directories(root: Path, paths: list[Path]) -> None:
    missing = [path for path in paths if not path.is_dir()]
    if missing:
        fail(
            "Missing required directories: "
            + ", ".join(relative(path, root) for path in missing)
        )


def load_yaml(path: Path, root: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"Unable to parse {relative(path, root)}: {exc}")


def parse_application_metadata(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception as exc:
        fail(f"Unable to read {path}: {exc}")

    metadata: dict[str, str] = {}
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            fail(f"{path}:{line_number}: expected 'key = value'")
        key, value = (part.strip() for part in line.split("=", 1))
        if not key or not value:
            fail(f"{path}:{line_number}: key and value must be non-empty")
        if key in metadata:
            fail(f"{path}:{line_number}: duplicate key {key!r}")
        metadata[key] = value

    app_type = metadata.get("type")
    if not app_type:
        fail(f"{path}: missing mandatory key 'type'")
    if app_type not in SUPPORTED_APP_TYPES:
        fail(f"{path}: unsupported application type {app_type!r}")
    return metadata


def is_application_directory_name(name: str) -> bool:
    if name in COMPACT_APPLICATION_NAMES:
        return True
    return name.startswith("digitalhouses_") and name != "digitalhouses_"


def discover_applications(root: Path) -> list[Path]:
    apps = sorted(
        path
        for path in root.iterdir()
        if path.is_dir() and is_application_directory_name(path.name)
    )
    if not apps:
        fail("No DigitalHouses applications found")
    return apps


def validate_common(root: Path, app: Path, metadata: dict[str, str]) -> None:
    if not is_application_directory_name(app.name):
        fail(f"Invalid application directory name: {app.name}")

    require_files(
        root,
        [
            app / "digitalhouses.app",
            app / "README.md",
            app / "CHANGELOG.md",
        ],
    )
    require_directories(root, [app / "tests"])

    if not list((app / "tests").glob("test_*.py")):
        fail(f"{app.name}/tests must contain at least one test_*.py")

    if metadata.get("type") not in SUPPORTED_APP_TYPES:
        fail(f"Unsupported application type for {app.name}: {metadata.get('type')!r}")
