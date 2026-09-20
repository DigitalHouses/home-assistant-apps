#!/usr/bin/env python3
"""Release contract for DigitalHouses monorepo products."""

from __future__ import annotations

import argparse
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_SEMVER_RE = re.compile(
    r"^(?P<major>0|[1-9]\d*)\."
    r"(?P<minor>0|[1-9]\d*)\."
    r"(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<pre>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+(?P<build>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


class ReleaseContractError(RuntimeError):
    """Raised when a requested release violates the repository contract."""


@dataclass(frozen=True)
class ProductSpec:
    identifier: str
    title: str
    directory: str
    version_source: str
    policy_baseline: str


@dataclass(frozen=True)
class ReleaseMetadata:
    product: str
    version: str
    tag: str
    title: str
    notes: str
    prerelease: bool


PRODUCTS = {
    "digitalhouses_pve_agent": ProductSpec(
        identifier="digitalhouses_pve_agent",
        title="DigitalHouses PVE Agent",
        directory="dh_pve_app",
        version_source="version_file",
        policy_baseline="0.5.6",
    ),
    "digitalhouses_plex_agent": ProductSpec(
        identifier="digitalhouses_plex_agent",
        title="DigitalHouses Plex Agent",
        directory="digitalhouses_plex_monitoring",
        version_source="version_file",
        policy_baseline="0.2.2",
    ),
    "digitalhouses_recorder_app": ProductSpec(
        identifier="digitalhouses_recorder_app",
        title="DigitalHouses Recorder App",
        directory="digitalhouses_db_monitoring",
        version_source="haos_config",
        policy_baseline="0.1.8",
    ),
    "digitalhouses_speedtest_app": ProductSpec(
        identifier="digitalhouses_speedtest_app",
        title="DigitalHouses Speedtest App",
        directory="digitalhouses_speedtest",
        version_source="haos_config",
        policy_baseline="1.2.1",
    ),
}


def _parse_semver(version: str) -> tuple[tuple[int, int, int], tuple[str, ...] | None]:
    match = _SEMVER_RE.fullmatch(version)
    if match is None:
        raise ReleaseContractError(f"invalid semantic version: {version}")
    core = (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
    )
    prerelease = match.group("pre")
    return core, tuple(prerelease.split(".")) if prerelease else None


def _compare_prerelease(
    left: tuple[str, ...] | None,
    right: tuple[str, ...] | None,
) -> int:
    if left is None and right is None:
        return 0
    if left is None:
        return 1
    if right is None:
        return -1

    for left_part, right_part in zip(left, right):
        if left_part == right_part:
            continue

        left_numeric = left_part.isdigit()
        right_numeric = right_part.isdigit()
        if left_numeric and right_numeric:
            return -1 if int(left_part) < int(right_part) else 1
        if left_numeric != right_numeric:
            return -1 if left_numeric else 1
        return -1 if left_part < right_part else 1

    if len(left) == len(right):
        return 0
    return -1 if len(left) < len(right) else 1


def compare_semver(left: str, right: str) -> int:
    left_core, left_pre = _parse_semver(left)
    right_core, right_pre = _parse_semver(right)

    if left_core != right_core:
        return -1 if left_core < right_core else 1
    return _compare_prerelease(left_pre, right_pre)


def _read_haos_config_version(path: Path) -> str:
    version_re = re.compile(
        r"^version:\s*['\"]?(?P<version>[^'\"\s#]+)['\"]?\s*(?:#.*)?$"
    )
    matches: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = version_re.match(line)
        if match:
            matches.append(match.group("version"))

    if len(matches) != 1:
        raise ReleaseContractError(
            f"{path}: expected exactly one top-level version field"
        )
    return matches[0]


def _source_version(root: Path, spec: ProductSpec) -> str:
    product_dir = root / spec.directory
    if spec.version_source == "version_file":
        path = product_dir / "VERSION"
        if not path.is_file():
            raise ReleaseContractError(f"missing release version file: {path}")
        return path.read_text(encoding="utf-8").strip()

    if spec.version_source == "haos_config":
        path = product_dir / "config.yaml"
        if not path.is_file():
            raise ReleaseContractError(f"missing Home Assistant App config: {path}")
        return _read_haos_config_version(path)

    raise ReleaseContractError(
        f"unsupported version source for {spec.identifier}: {spec.version_source}"
    )


def _changelog_section(text: str, heading: str) -> str | None:
    lines = text.splitlines()
    start: int | None = None

    for index, line in enumerate(lines):
        if line.strip() == f"## {heading}":
            start = index + 1
            break

    if start is None:
        return None

    end = len(lines)
    for index in range(start, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break

    return "\n".join(lines[start:end]).strip()


def release_metadata(
    root: Path,
    *,
    product: str,
    version: str,
) -> ReleaseMetadata:
    spec = PRODUCTS.get(product)
    if spec is None:
        raise ReleaseContractError(f"unknown release product: {product}")

    _parse_semver(version)

    if compare_semver(version, spec.policy_baseline) <= 0:
        raise ReleaseContractError(
            f"{product} {version} is not newer than policy baseline "
            f"{spec.policy_baseline}"
        )

    source_version = _source_version(root, spec)
    if source_version != version:
        raise ReleaseContractError(
            f"{product} source version is {source_version}, requested {version}"
        )

    changelog_path = root / spec.directory / "CHANGELOG.md"
    if not changelog_path.is_file():
        raise ReleaseContractError(f"missing changelog: {changelog_path}")

    changelog = changelog_path.read_text(encoding="utf-8")
    unreleased = _changelog_section(changelog, "Unreleased")
    if unreleased:
        raise ReleaseContractError(
            f"{product} changelog still has non-empty Unreleased content"
        )

    notes = _changelog_section(changelog, version)
    if not notes:
        raise ReleaseContractError(
            f"{product} changelog has no non-empty section for {version}"
        )

    _, prerelease = _parse_semver(version)
    return ReleaseMetadata(
        product=product,
        version=version,
        tag=f"{spec.identifier}-v{version}",
        title=f"{spec.title} v{version}",
        notes=notes,
        prerelease=prerelease is not None,
    )


def _git_tags(root: Path, prefix: str) -> list[str]:
    result = subprocess.run(
        ["git", "tag", "--list", f"{prefix}-v*"],
        cwd=root,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def validate_git_release_history(root: Path, metadata: ReleaseMetadata) -> None:
    existing_tags = _git_tags(root, metadata.product)
    if metadata.tag in existing_tags:
        raise ReleaseContractError(f"release tag already exists: {metadata.tag}")

    prefix = f"{metadata.product}-v"
    existing_versions: list[str] = []
    for tag in existing_tags:
        version = tag.removeprefix(prefix)
        _parse_semver(version)
        existing_versions.append(version)

    newer_or_equal = [
        version
        for version in existing_versions
        if compare_semver(metadata.version, version) <= 0
    ]
    if newer_or_equal:
        newest = newer_or_equal[0]
        for candidate in newer_or_equal[1:]:
            if compare_semver(candidate, newest) > 0:
                newest = candidate
        raise ReleaseContractError(
            f"requested version {metadata.version} is not newer than "
            f"existing release {newest}"
        )


def _write_github_output(path: Path, metadata: ReleaseMetadata) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"tag={metadata.tag}\n")
        handle.write(f"title={metadata.title}\n")
        handle.write(
            f"prerelease={'true' if metadata.prerelease else 'false'}\n"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--product", required=True, choices=sorted(PRODUCTS))
    parser.add_argument("--version", required=True)
    parser.add_argument("--notes-file", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()

    try:
        metadata = release_metadata(
            ROOT,
            product=args.product,
            version=args.version,
        )
        validate_git_release_history(ROOT, metadata)
    except (ReleaseContractError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"RELEASE VALIDATION FAILED: {exc}") from exc

    args.notes_file.write_text(metadata.notes + "\n", encoding="utf-8")
    if args.github_output is not None:
        _write_github_output(args.github_output, metadata)

    print(f"Release validation passed: {metadata.tag}")


if __name__ == "__main__":
    main()
