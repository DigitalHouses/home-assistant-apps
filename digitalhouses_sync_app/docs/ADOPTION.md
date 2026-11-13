# DH Sync — Plex adoption preflight (development preview)

**Status:** implemented audit and opt-in reference receipt; no live HA deployment, no YAML write path. Requires PR review, release tests and controlled pilot before production use.

## Why Storage is blocked

The approved Plex view is currently embedded in the HOME Storage dashboard (historically reported as \`/config/.storage/lovelace.dashboard_system\`, view \`dh-plex-agent\`). Direct JSON edits are unsupported and unsafe. The preflight reads Storage, compares the full view with the canonical Git file, then reports \`blocked_identical_storage_view\` or \`blocked_different_storage_view\`. It **never** migrates, deletes or duplicates the view. If the same path is found twice, it blocks.

A two-phase Storage → managed YAML engine now exists under [STORAGE_MIGRATION.md](STORAGE_MIGRATION.md), but lacks the production HA WebSocket bridge and live acceptance. The actual conversion still needs an explicit reversible migration workflow, UI operator consent and live acceptance. Until that is implemented, existing Plex views remain untouched in their current dashboard. The absence of a found Storage view does not itself authorize creating a new one.

## Recorder: safe adoption without reinstallation

The already enabled package may be at \`/config/packages/DH/dh_plex_app_package.yaml\`. The app checks the current package loader contract (\`!include_dir_merge_named packages/\`), scans all YAML package files for the exact historical top-level key \`dh_app_plex_monitoring_package\`, refuses duplicates, and compares the **parsed YAML** of the installed file against the canonical resource.

The preflight's pinned resources are read from immutable merge commit:

\`d4e99ac789b6bd53c4185bff0612edff5427d315\`

Canonical files:
- \`digitalhouses_plex_agent/dashboards/ru/10_plex.yaml\`
- \`digitalhouses_plex_agent/packages/common/dh_plex_app_package.yaml\`

A positive preflight is only a match in contents. It does not prove which agent version is **currently running**, nor does it confirm HACS dependencies or HA configuration validity.

## Developer CLI (not an installed user interface)

From within the **development container** with a read-only Home Assistant configuration mount:

\`\`\`sh
python3 /app/adoption.py audit-plex
\`\`\`

To record a matching installed Recorder without changing or replacing the file (explicit opt-in):

\`\`\`sh
python3 /app/adoption.py record-plex-recorder --confirm-existing-only
\`\`\`

Only the second command may create \`/data/plex_recorder_adoption.json\`. The receipt preserves the installed file's SHA-256, its original relative path, the semantic canonical SHA-256, and the immutable Git revision. An existing different receipt is never overwritten. If the installed file changes after the audit, the receipt operation refuses it. Running it again with unchanged content is idempotent.

**No user action is required now.** This is engineering acceptance infrastructure, not a production installation guide.

## Always blocked until separate implementation

- Writing \`/homeassistant/.storage\` or modifying the Storage parent dashboard
- Installing a duplicate Plex Recorder package or changing its top-level key
- Editing \`/homeassistant/configuration.yaml\` or adding a second panel automatically
- Applying a new YAML generation, reloading HA or restarting HA
- Declaring the installed agent compatible without a live MQTT version observation
- Claiming rollback of HA YAML when no HA YAML changes have been made

The current App mount remains \`homeassistant_config: read_only: true\`. Existing Recorder and Storage files are neither changed nor backed up during this step, because the adapter does not write them. The \`/data\` receipt is merely an audit record.
