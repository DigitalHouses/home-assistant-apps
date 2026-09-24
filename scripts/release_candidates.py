#!/usr/bin/env python3
"""Detect product releases introduced by a repository change."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from release_contract import (
    PRODUCTS,
    ReleaseContractError,
    _source_version,
    compare_semver,
    release_metadata,
    validate_git_release_history,
)

ROOT = Path(__file__).resolve().parents[1]

_HAOS_VERSION_RE = re.compile(
    r"^version:\s*['\"]?(?P<version>[^'\"\s#]+)['\"]?\s*(?:#.*)?$"
)


@dataclass(frozen=True)
class ReleaseCandidate:
    product: str
    version: str

    def as_dict(self) -> dict[str, str]:
        return {"product": self.product, "version": self.version}


def version_source_path(product: str) -> str:
    spec = PRODUCTS[product]
    filename = "VERSION" if spec.version_source == "version_file" else "config.yaml"
    return f"{spec.directory}/{filename}"


def _version_from_text(product: str, text: str) -> str:
    spec = PRODUCTS[product]
    if spec.version_source == "version_file":
        version = text.strip()
        if not version:
            raise ReleaseContractError(f"{product}: empty VERSION")
        return version

    if spec.version_source == "haos_config":
        matches: list[str] = []
        for line in text.splitlines():
            match = _HAOS_VERSION_RE.match(line)
            if match:
                matches.append(match.group("version"))
        if len(matches) != 1:
            raise ReleaseContractError(
                f"{product}: expected exactly one top-level config version"
            )
        return matches[0]

    raise ReleaseContractError(
        f"{product}: unsupported version source {spec.version_source}"
    )


def _git_show(root: Path, revision: str, path: str) -> str | None:
    result = subprocess.run(
        ["git", "show", f"{revision}:{path}"],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode == 0:
        return result.stdout
    if "does not exist" in result.stderr or "exists on disk, but not in" in result.stderr:
        return None
    raise ReleaseContractError(
        f"git show failed for {revision}:{path}: {result.stderr.strip()}"
    )


def changed_release_candidates(
    root: Path,
    *,
    base: str,
    head: str,
) -> list[ReleaseCandidate]:
    candidates: list[ReleaseCandidate] = []

    for product in sorted(PRODUCTS):
        path = version_source_path(product)
        before_text = _git_show(root, base, path)
        after_text = _git_show(root, head, path)

        if after_text is None:
            if before_text is not None:
                raise ReleaseContractError(
                    f"{product}: version source was removed: {path}"
                )
            continue

        after_version = _version_from_text(product, after_text)
        before_version = (
            _version_from_text(product, before_text)
            if before_text is not None
            else None
        )

        if before_version != after_version:
            candidates.append(
                ReleaseCandidate(product=product, version=after_version)
            )

    return candidates


def _git_tags(root: Path, product: str) -> list[str]:
    result = subprocess.run(
        ["git", "tag", "--list", f"{product}-v*"],
        cwd=root,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def pending_existing_release_candidates(root: Path) -> list[ReleaseCandidate]:
    """Return unreleased current versions only for already-adopted products.

    A product is considered already adopted when it has at least one canonical
    release tag. This prevents enabling automation from unexpectedly publishing
    first releases for products that have never entered the release flow.
    """

    candidates: list[ReleaseCandidate] = []

    for product, spec in sorted(PRODUCTS.items()):
        tags = _git_tags(root, product)
        if not tags:
            continue

        versions = [tag.removeprefix(f"{product}-v") for tag in tags]
        newest = versions[0]
        for version in versions[1:]:
            if compare_semver(version, newest) > 0:
                newest = version

        current = _source_version(root, spec)
        if compare_semver(current, newest) > 0:
            candidates.append(ReleaseCandidate(product=product, version=current))

    return candidates


def merge_candidates(*groups: list[ReleaseCandidate]) -> list[ReleaseCandidate]:
    merged: dict[str, ReleaseCandidate] = {}
    for group in groups:
        for candidate in group:
            previous = merged.get(candidate.product)
            if previous is not None and previous.version != candidate.version:
                raise ReleaseContractError(
                    f"{candidate.product}: conflicting release candidates "
                    f"{previous.version} and {candidate.version}"
                )
            merged[candidate.product] = candidate
    return [merged[key] for key in sorted(merged)]


def validate_candidates(root: Path, candidates: list[ReleaseCandidate]) -> None:
    for candidate in candidates:
        metadata = release_metadata(
            root,
            product=candidate.product,
            version=candidate.version,
        )
        validate_git_release_history(root, metadata)


def _write_github_output(path: Path, candidates: list[ReleaseCandidate]) -> None:
    payload = json.dumps([item.as_dict() for item in candidates], separators=(",", ":"))
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"has_candidates={'true' if candidates else 'false'}\n")
        handle.write(f"candidates={payload}\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--include-pending-existing", action="store_true")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()

    try:
        changed = changed_release_candidates(
            ROOT,
            base=args.base,
            head=args.head,
        )
        pending = (
            pending_existing_release_candidates(ROOT)
            if args.include_pending_existing
            else []
        )
        candidates = merge_candidates(changed, pending)
        if args.validate:
            validate_candidates(ROOT, candidates)
    except (ReleaseContractError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"RELEASE CANDIDATE VALIDATION FAILED: {exc}") from exc

    payload = [item.as_dict() for item in candidates]

    if args.json_output is not None:
        args.json_output.write_text(
            json.dumps(payload, indent=2) + "\n",
            encoding="utf-8",
        )

    if args.github_output is not None:
        _write_github_output(args.github_output, candidates)

    if candidates:
        for candidate in candidates:
            print(f"Release candidate: {candidate.product} {candidate.version}")
    else:
        print("No release candidates")


if __name__ == "__main__":
    main()
