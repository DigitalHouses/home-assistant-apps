#!/usr/bin/env python3
"""Repository-level validation for DigitalHouses products."""

from __future__ import annotations

import json
import re
from pathlib import Path

from validators.common import (
    ValidationError,
    discover_applications,
    parse_application_metadata,
    require_files,
    validate_common,
)
from validators.products.backblaze_app import validate_backblaze
from validators.products.internet_app import validate_internet
from validators.products.plex_agent import validate_plex_agent
from validators.products.pve_agent import validate_dh_pve_app
from validators.products.recorder_app import validate_db_monitoring
from validators.products.speedtest_app import validate_speedtest
from validators.types.haos_app import validate_haos_addon
from validators.types.linux_agent import validate_linux_agent

ROOT = Path(__file__).resolve().parents[1]

TYPE_VALIDATORS = {
    "haos_addon": validate_haos_addon,
    "linux_agent": validate_linux_agent,
}

PRODUCT_TYPE_TO_APPLICATION_TYPE = {
    "app": "haos_addon",
    "agent": "linux_agent",
}

PRODUCT_VALIDATORS = {
    "digitalhouses_backblaze_app": validate_backblaze,
    "digitalhouses_internet_app": validate_internet,
    "digitalhouses_plex_agent": validate_plex_agent,
    "digitalhouses_pve_agent": validate_dh_pve_app,
    "digitalhouses_recorder_app": validate_db_monitoring,
    "digitalhouses_speedtest_app": validate_speedtest,
}

_PRODUCT_ID_RE = re.compile(
    r"^digitalhouses_(?P<function>[a-z0-9]+(?:_[a-z0-9]+)*)_(?P<type>app|agent)$"
)


def validate_product_registry_naming(registry: dict) -> None:
    products = registry.get("products")
    if not isinstance(products, list):
        raise ValidationError("product registry must contain a products list")

    seen_ids: set[str] = set()
    seen_directories: set[str] = set()

    for entry in products:
        if not isinstance(entry, dict):
            raise ValidationError("product registry entries must be mappings")

        identifier = entry.get("id")
        if not isinstance(identifier, str):
            raise ValidationError("product registry entry has no string id")
        if identifier in seen_ids:
            raise ValidationError(f"duplicate product registry id: {identifier}")
        seen_ids.add(identifier)

        match = _PRODUCT_ID_RE.fullmatch(identifier)
        if match is None:
            raise ValidationError(
                f"invalid canonical product id: {identifier}; expected "
                "digitalhouses_<function>_<app|agent>"
            )

        expected_type = match.group("type")
        product_type = entry.get("type")
        if product_type != expected_type:
            raise ValidationError(
                f"{identifier}: registry type must be {expected_type}, "
                f"got {product_type!r}"
            )

        expected_prefix = f"dh_{match.group('function')}_{expected_type}"
        entity_prefix = entry.get("entity_prefix")
        if entity_prefix != expected_prefix:
            raise ValidationError(
                f"{identifier}: entity_prefix must be {expected_prefix}, "
                f"got {entity_prefix!r}"
            )

        display_name = entry.get("display_name")
        expected_display_suffix = "App" if product_type == "app" else "Agent"
        if (
            not isinstance(display_name, str)
            or not display_name.endswith(f" {expected_display_suffix}")
        ):
            raise ValidationError(
                f"{identifier}: display_name must end with {expected_display_suffix!r}"
            )

        release = entry.get("release")
        if release is not None:
            if not isinstance(release, dict):
                raise ValidationError(f"{identifier}: release must be a mapping or null")
            expected_title = f"DigitalHouses {display_name}"
            if release.get("title") != expected_title:
                raise ValidationError(
                    f"{identifier}: release title must be {expected_title!r}"
                )

        repository_directory = entry.get("repository_directory")
        if repository_directory is not None:
            if repository_directory != identifier:
                raise ValidationError(
                    f"{identifier}: repository_directory must equal canonical id"
                )
            if repository_directory in seen_directories:
                raise ValidationError(
                    f"duplicate repository_directory: {repository_directory}"
                )
            seen_directories.add(repository_directory)
        elif release is not None:
            raise ValidationError(
                f"{identifier}: release-managed product must have repository_directory"
            )

        if product_type == "app":
            haos_slug = entry.get("haos_slug")
            if not isinstance(haos_slug, str) or not haos_slug:
                raise ValidationError(
                    f"{identifier}: Home Assistant App must declare haos_slug"
                )

            migration = entry.get("slug_migration")
            if haos_slug == identifier:
                if migration is not None:
                    raise ValidationError(
                        f"{identifier}: canonical haos_slug must not carry pending migration"
                    )
            elif repository_directory is not None:
                if migration != {
                    "status": "pending_controlled_reinstall",
                    "target": identifier,
                }:
                    raise ValidationError(
                        f"{identifier}: legacy haos_slug requires explicit "
                        "pending_controlled_reinstall migration to canonical id"
                    )
        elif "haos_slug" in entry or "slug_migration" in entry:
            raise ValidationError(
                f"{identifier}: Linux Agent must not declare Home Assistant App slug metadata"
            )


def validate_repository(root: Path = ROOT) -> list[dict[str, str]]:
    require_files(
        root,
        [
            root / "repository.yaml",
            root / "README.md",
            root / "LICENSE",
            root / "docs/standards/DIGITALHOUSES_APP_STANDARD.md",
            root / "docs/standards/PRODUCT_NAMING_STANDARD.md",
            root / "docs/standards/EVENTS_AND_NOTIFICATIONS_STANDARD.md",
            root / "docs/standards/RELEASE_POLICY.md",
            root / "docs/standards/REPOSITORY_GOVERNANCE.md",
            root / "scripts/release_contract.py",
            root / "scripts/release_candidates.py",
            root / "digitalhouses-stats/digitalhouses_stats/product_registry.json",
            root / ".github/workflows/validate.yml",
            root / ".github/workflows/auto-merge.yml",
        ],
    )

    registry_path = (
        root / "digitalhouses-stats/digitalhouses_stats/product_registry.json"
    )
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    validate_product_registry_naming(registry)

    registered_entries = [
        entry
        for entry in registry["products"]
        if entry.get("repository_directory") is not None
    ]
    registered_directories = {
        entry["repository_directory"] for entry in registered_entries
    }

    marker_directories = {app.name for app in discover_applications(root)}
    unregistered = sorted(marker_directories - registered_directories)
    if unregistered:
        raise ValidationError(
            "applications missing from product registry: "
            + ", ".join(unregistered)
        )

    missing = sorted(registered_directories - marker_directories)
    if missing:
        raise ValidationError(
            "registered products missing implementation directory: "
            + ", ".join(missing)
        )

    results: list[dict[str, str]] = []
    for entry in registered_entries:
        identifier = entry["id"]
        app = root / entry["repository_directory"]

        metadata = parse_application_metadata(app / "digitalhouses.app")
        expected_application_type = PRODUCT_TYPE_TO_APPLICATION_TYPE[entry["type"]]
        if metadata["type"] != expected_application_type:
            raise ValidationError(
                f"{identifier}: digitalhouses.app type must be "
                f"{expected_application_type}, got {metadata['type']!r}"
            )

        validate_common(root, app, metadata)
        context = TYPE_VALIDATORS[metadata["type"]](root, app)

        if entry["type"] == "app":
            config = context["config"]
            expected_slug = entry["haos_slug"]
            if config.get("slug") != expected_slug:
                raise ValidationError(
                    f"{identifier}: config slug must equal registry haos_slug "
                    f"{expected_slug!r}, got {config.get('slug')!r}"
                )
            if expected_slug == identifier and config.get("slug") != identifier:
                raise ValidationError(
                    f"{identifier}: completed App slug migration regressed"
                )

            expected_name = f"DigitalHouses {entry['display_name']}"
            if config.get("name") != expected_name:
                raise ValidationError(
                    f"{identifier}: config name must be {expected_name!r}, "
                    f"got {config.get('name')!r}"
                )

        product_validator = PRODUCT_VALIDATORS.get(identifier)
        if product_validator is None:
            raise ValidationError(
                f"{identifier}: registered implementation has no product validator"
            )
        product_validator(root, app, context)

        results.append(
            {
                "name": identifier,
                "type": metadata["type"],
                "version": str(context["version"]),
            }
        )
    return results


def main() -> None:
    try:
        results = validate_repository()
    except ValidationError as exc:
        raise SystemExit(f"VALIDATION FAILED: {exc}") from exc

    print("Repository validation passed")
    for result in results:
        print(
            f"{result['name']}: "
            f"type={result['type']} version={result['version']}"
        )


if __name__ == "__main__":
    main()
