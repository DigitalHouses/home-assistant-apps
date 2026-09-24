#!/usr/bin/env python3
"""Repository-level validation for DigitalHouses applications."""

from __future__ import annotations

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


def validate_repository(root: Path = ROOT) -> list[dict[str, str]]:
    require_files(
        root,
        [
            root / "repository.yaml",
            root / "README.md",
            root / "LICENSE",
            root / "docs/standards/DIGITALHOUSES_APP_STANDARD.md",
            root / "docs/standards/EVENTS_AND_NOTIFICATIONS_STANDARD.md",
            root / "docs/standards/RELEASE_POLICY.md",
            root / "docs/standards/REPOSITORY_GOVERNANCE.md",
            root / "scripts/release_contract.py",
            root / "scripts/release_candidates.py",
            root / ".github/workflows/validate.yml",
            root / ".github/workflows/auto-merge.yml",
        ],
    )

    results: list[dict[str, str]] = []
    for app in discover_applications(root):
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
