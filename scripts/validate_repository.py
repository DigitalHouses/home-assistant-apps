#!/usr/bin/env python3
"""Repository-level validation for DigitalHouses applications."""

from __future__ import annotations

import json
import re
from pathlib import Path

from validators.products.backblaze_app import validate_backblaze
from validators.products.recorder_app import validate_db_monitoring
from validators.products.pve_agent import validate_dh_pve_app
from validators.products.plex_agent import validate_plex_monitoring
from validators.products.speedtest_app import validate_speedtest
from validators.products.internet_app import validate_internet
from validators.common import (
    ValidationError,
    discover_applications,
    parse_application_metadata,
    require_files,
    validate_common,
)
from validators.types.haos_app import validate_haos_addon
from validators.types.linux_agent import validate_linux_agent

ROOT = Path(__file__).resolve().parents[1]

TYPE_VALIDATORS = {
    "haos_addon": validate_haos_addon,
    "linux_agent": validate_linux_agent,
}

PRODUCT_VALIDATORS = {
    "digitalhouses_backblaze": validate_backblaze,
    "digitalhouses_speedtest": validate_speedtest,
    "dh_internet_app": validate_internet,
    "digitalhouses_db_monitoring": validate_db_monitoring,
    "digitalhouses_plex_monitoring": validate_plex_monitoring,
    "dh_pve_app": validate_dh_pve_app,
}

_PRODUCT_ID_RE = re.compile(
    r"^digitalhouses_(?P<function>[a-z0-9]+(?:_[a-z0-9]+)*)_(?P<type>app|agent)$"
)


def validate_product_registry_naming(registry: dict) -> None:
    products = registry.get("products")
    if not isinstance(products, list):
        raise ValidationError("product registry must contain a products list")

    for entry in products:
        identifier = entry.get("id")
        if not isinstance(identifier, str):
            raise ValidationError("product registry entry has no string id")

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

        expected_prefix = (
            f"dh_{match.group('function')}_{expected_type}"
        )
        entity_prefix = entry.get("entity_prefix")
        if entity_prefix != expected_prefix:
            raise ValidationError(
                f"{identifier}: entity_prefix must be {expected_prefix}, "
                f"got {entity_prefix!r}"
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

    registered_directories = {
        entry.get("repository_directory")
        for entry in registry["products"]
        if entry.get("repository_directory")
    }

    applications = discover_applications(root)
    unregistered = sorted(
        app.name for app in applications if app.name not in registered_directories
    )
    if unregistered:
        raise ValidationError(
            "applications missing from product registry: "
            + ", ".join(unregistered)
        )

    results: list[dict[str, str]] = []
    for app in applications:
        metadata = parse_application_metadata(app / "digitalhouses.app")
        validate_common(root, app, metadata)

        app_type = metadata["type"]
        type_validator = TYPE_VALIDATORS[app_type]
        context = type_validator(root, app)

        app_validator = PRODUCT_VALIDATORS.get(app.name)
        if app_validator is not None:
            app_validator(root, app, context)

        results.append(
            {
                "name": app.name,
                "type": app_type,
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
