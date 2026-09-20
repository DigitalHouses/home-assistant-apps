# Contributing to DigitalHouses Home Assistant Apps

Thank you for contributing to DigitalHouses.

This repository contains Home Assistant Apps and Linux agents that integrate with Home Assistant. Keep changes focused on one product or one repository-level concern whenever possible.

## Before opening a pull request

For bug fixes and small improvements, a pull request can be opened directly.

For changes that affect architecture, shared contracts, application naming, installation behavior, MQTT conventions, compatibility, or more than one product, open an issue first so the design can be agreed before implementation.

## Repository model

DigitalHouses components use two delivery types:

- **Home Assistant App** — runs under Home Assistant Supervisor.
- **Linux agent** — runs natively on the target Linux host and integrates with Home Assistant, typically through MQTT Discovery.

Shared repository contracts live under `docs/standards/`. Product-specific engineering records live under `docs/<product>/`.

Repository validation follows three layers:

```text
common
└── type
    └── product
```

The implementation is under `scripts/validators/`.

Repository workflow follows [DigitalHouses Repository Governance](../docs/standards/REPOSITORY_GOVERNANCE.md). Product releases follow [DigitalHouses Release Policy](../docs/standards/RELEASE_POLICY.md).

## Development

Use the supported Python version from the repository CI workflow.

Before submitting a pull request, run:

```bash
python scripts/validate_repository.py
python -m unittest discover -s scripts/tests -v
```

Also run the tests for the product you changed. The complete required checks are defined in `.github/workflows/validate.yml`.

## Documentation

Update documentation when a change affects installation, configuration, behavior, compatibility, diagnostics, or user-visible entities.

Architecture specifications and implementation plans should stay with the product they describe. Shared rules belong in `docs/standards/`.

## Pull requests

A good pull request should:

- have one clear purpose;
- identify the affected product;
- explain user-visible behavior changes;
- include tests for changed behavior;
- keep unrelated formatting or refactoring out of the diff;
- update documentation and changelog when applicable;
- pass all repository CI checks.

Do not include credentials, tokens, private hostnames, private IP inventory, production configuration, or other sensitive deployment data.

## Source of truth

GitHub is the source of truth for reusable DigitalHouses application code, engineering history, and release provenance. Production systems are deployment targets, not canonical source repositories.

## License

By contributing, you agree that your contribution is provided under the repository's MIT License.
