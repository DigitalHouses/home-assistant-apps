# DigitalHouses Sync App

**Status: development preview, not a production release.** No GHCR image for version 0.0.1 is published and the App must not be installed on production Home Assistant.

Canonical product ID and HAOS slug: `digitalhouses_sync_app`. Type: `haos_addon`. Home Assistant entities: `dh_sync_app_*`.

## Purpose

Synchronize DigitalHouses-maintained YAML dashboards and packages from `DigitalHouses/home-assistant-apps` into local HAOS configuration. A single `DigitalHouses` sidebar dashboard will contain only views of installed DigitalHouses products.

The App **does not** update Agent/App executable code. It is independent of Ansible and of any specific customer site or CORE host.

## Current implementation

The 0.0.1 source contains a conservative, read-only MQTT availability observer. It stores seen product identities in its own /data/inventory.json and publishes the App's canonical version/started-at diagnostics through MQTT Discovery. It does NOT download GitHub YAML, register a dashboard, write to Home Assistant config, validate HA packages, or apply updates.

The HA configuration is mapped **read-only** in this development phase to make accidental writes impossible.

## Planned v1 behavior

- MQTT product discovery and remembered installation inventory; offline is not uninstall.
- Select tested YAML by installed product version and locale from immutable Git ref.
- Stage and validate the complete update, preserve last working generation, and roll back safely.
- Assemble one `digital-houses` YAML dashboard with dynamic view ordering.
- Show a restart-required state for HA package changes. Never restart HA automatically.
- Configurable interval (default 24 h) and explicit manual synchronization.
- No auxiliary VM, database, CI runner, HACS manager, or agent code updater.

See [DOCS.md](DOCS.md), [Architecture](docs/ARCHITECTURE.md), and [Product requirements](docs/PRODUCT_REQUIREMENTS.md) once added.

## Release constraints

Production install must follow the shared registry, build, release, GHCR immutability, diagnostics and telemetry/privacy policies. Do not publish 0.0.1 from this design branch until those obligations and end-to-end tests are satisfied.

