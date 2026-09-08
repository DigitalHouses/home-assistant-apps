from __future__ import annotations

from pathlib import Path

from .models import BuildInfo


class BuildInfoError(ValueError):
    pass


def _parse_flat(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line_number, raw in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise BuildInfoError(
                f"{path}:{line_number}: expected key = value"
            )
        key, value = (part.strip() for part in line.split("=", 1))
        if not key or not value:
            raise BuildInfoError(
                f"{path}:{line_number}: empty build-info key/value"
            )
        if key in result:
            raise BuildInfoError(
                f"{path}:{line_number}: duplicate key {key!r}"
            )
        result[key] = value
    return result


def load_build_info(app_root: Path) -> BuildInfo:
    version_path = app_root / "VERSION"
    if not version_path.is_file():
        raise BuildInfoError(f"missing VERSION: {version_path}")
    version = version_path.read_text(encoding="utf-8").strip()
    if not version:
        raise BuildInfoError("VERSION is empty")

    build_path = app_root / "BUILD_INFO"
    if not build_path.is_file():
        return BuildInfo(version=version, source="local", commit="unknown")

    data = _parse_flat(build_path)
    stored_version = data.get("version")
    source = data.get("source")
    commit = data.get("commit")
    if not stored_version or not source or not commit:
        raise BuildInfoError("BUILD_INFO requires version, source and commit")
    if stored_version != version:
        raise BuildInfoError(
            f"BUILD_INFO version {stored_version!r} does not match VERSION {version!r}"
        )
    return BuildInfo(version=version, source=source, commit=commit)
