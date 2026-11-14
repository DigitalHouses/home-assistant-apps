# DH Sync v1 — architecture decision record

Status: implementation plan; operator-approved direction, not proof of operational acceptance.

## Boundary
- HAOS App `digitalhouses_sync_app` runs locally with Supervisor.
- GitHub is source of truth for YAML. HA renders only local YAML.
- Installed products own data acquisition, MQTT Discovery, version diagnostics, and executable-code updates.
- DH Sync owns the YAML delivery and the one DigitalHouses dashboard.
- No Ansible CORE, central server, VM/LXC, private tenant addressing, or remote home access is required.

## Discovery
Observe existing product-level MQTT `availability` topics and Discovery metadata. Preserve product identity once positively observed. An offline or missing topic never removes a view. Uninstall is explicit and authoritative; in v1, operator confirmation in DH Sync is sufficient. Do not silently interpret missing sensors as removal.

Existing MQTT names remain unchanged; normalization belongs in a small DH Sync adapter list until all products publish a common discoverable contract. Never add mandatory extra heartbeat traffic just for UI composition.

## Files
Products own `dashboards/<locale>/*.yaml` and `packages/*.yaml`, which remain in their existing product directories. Package revision headers follow `HA_PACKAGE_VERSIONING_STANDARD.md`. New view headers must record a stable view ID, independent view revision, and tested compatibility when asserted. Do not use the Agent version as the view revision.

A common local HA dashboard uses `/homeassistant/dashboards/dh/ui.yaml`, `views/*.yaml`, and one dashboard registration package under `/homeassistant/packages/dh/`; exact HA YAML reload behavior must be verified against the pilot.

## Transaction concept
1. Resolve product inventory, locale, version and immutable Git commit/tag.
2. Download the entire compatible file set to a private staging directory.
3. Parse and check required metadata and dependencies; reject incompatible / malformed packages.
4. Compare hashes to detect local edits; preserve previous working generation.
5. Perform a Home Assistant configuration check and promote as one recoverable generation. An interrupted promote or failed validation restores the previous generation.
6. For view-only changes, allow user Refresh. For packages that cannot reload, display `restart required` without automatic restart.
7. GitHub errors leave old files intact.

## Explicitly out of v1
- App/Agent executable upgrades.
- A new database, central broker, file server, or CI infrastructure.
- Automatic HACS installation.
- Automatic HA restarts.
- Machine-local dashboard edits merged into canonical files.
- Mass rollout or changes to existing Home Assistant sites.

