# DH Sync — Storage to managed YAML migration engine

**Status:** two-phase engine with fake Home Assistant tests, NOT live-deployed. This document supersedes the earlier "all Storage is blocked" wording only for an explicitly prepared, operator-confirmed pilot. The App still mounts HA configuration read-only and does not call this module automatically.

## Home Assistant API confirmed

Home Assistant 2026.10.4 code:
- \`lovelace/config\`: reads entire Storage dashboard; explicitly supply its dashboard URL path.
- \`lovelace/config/save\`: admin WebSocket command taking \`url_path\` and \`config\`. This is the only supported path for modifying the Storage dashboard.
- Independent on-disk verification of the Storage JSON is required: the save acknowledgment may occur before the store is durable. Verify and fail closed on mismatch.
- \`POST /api/config/core/check_config\` verifies the Home Assistant configuration. No automatic restart.
- A new YAML dashboard must be registered separately under \`lovelace.dashboards\` with slug \`digital-houses\`, YAML file \`dashboards/dh/ui.yaml\`, using \`views: !include_dir_list views\`. DH Sync **does not** blindly patch existing \`configuration.yaml\` and does not create a duplicate sidebar entry.

### Required pilot prerequisites

1. Source Storage URL path is determined from HA's actual dashboard registry. Do not derive it from \`.storage/lovelace.dashboard_system\`; the file key and URL path need not match.
2. A separately registered, accessible DigitalHouses YAML dashboard exists. The engine refuses unregistered or conflicting destination.
3. Operator confirms that the running Plex Agent is exactly 0.8.17 (only approved compatibility at current canonical view revision).
4. Canonical Plex view is pinned at merged source SHA \`d4e99ac789b6bd53c4185bff0612edff5427d315\`.
5. HA App gets a **reviewed and explicitly enabled** write mount for the migration operation. Its currently released preview mapping is read-only; **there is no production CLI for this migration yet**.
6. The HA admin bridge implementation must use the authenticated WebSocket and validate the persisted Storage result. It must also validate HA config and require actual user confirmation of the destination's rendered view.
7. No simultaneous dashboard edits during stage/cutover.

## Two phases with an explicit reversible checkpoint

**Stage**: compare complete original Storage dashboard to the canonical Plex view; require exactly one matching Plex view and no destination duplicate. Save full original Storage configuration to a restricted /data journal BEFORE writing. Create only the new managed view file using exclusive creation (never overwrite). Check HA config. Old Storage view remains untouched. An interruption leaves a recoverable journal.

**Cutover**: operator opens DigitalHouses and checks that the Plex view renders correctly; then confirms. Re-read the **entire** Storage dashboard and its persisted representation and require unchanged baseline. Re-read the target dashboard and check identical rendered Plex view; rerun HA config check. Use HA WebSocket \`lovelace/config/save\` to remove precisely one Plex view from the parent Storage dashboard (all other views retained). Verify API readback AND independent persisted Storage. Retain /data snapshot for rollback. On uncertain error, block and retain the journal for recovery; never overwrite newer user changes.

**Rollback**: require explicit confirmation; check source still matches either baseline or the exact expected post-cutover. Restore the whole backed-up Storage dashboard using WebSocket only if its current state matches the expected post-cutover snapshot. Independently confirm durability. Remove the managed Plex view only if its SHA matches our staged bytes. Refuse rollback overwriting any intervening manual edit.

## Current implementation boundary

Module: \`rootfs/app/storage_migration.py\`, tests \`tests/test_storage_migration.py\`.

It provides a pure migration engine and a strict \`HAStorage\` transport interface. Production wiring for authenticated WebSocket, target registration, actual live version observation, HACS diagnostics and operator UX remains pending. With a read-only HA mount, staging cannot run in an installed App, by design.

This is deliberate: **passing fake-HA transaction tests does not prove Home Assistant live migration or recovery**. No direct edits to \`.storage\`, Recorder, source App/Agent, Ansible, or live customer configurations are permitted here.
