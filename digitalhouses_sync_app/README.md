# DigitalHouses Sync App — 0.4.4

**Единый стандарт публикации YAML:** [DH Sync Resources Standard](../docs/standards/DH_SYNC_RESOURCES_STANDARD.md).

DH Sync automatically maintains Home Assistant dashboards and packages from public GitHub repositories owned by **DigitalHouses**. No prompts, buttons, token, paid plan, product allowlist or app-version checks.

## How it works

- On MQTT discovery and every hour, read a shared shallow public Git snapshot.
- Find canonical `dashboards/ru/*.yaml`, `packages/common/*.yaml`, and `packages/locales/ru/*.yaml` for every discovered product.
- Find local views by their Lovelace `path` and packages by their top-level YAML key. Preserve existing local filenames/paths.
- When bytes differ, save the original in private persistent `/data/dh-sync-auto/`, then replace the YAML atomically. No user confirmation.
- Retain other files untouched. Reject ambiguous duplicate view paths within the DigitalHouses YAML dashboard and duplicate package keys; Storage views in other dashboards use independent URL prefixes. Missing resources are normal.
- If interrupted mid-write, restore from the transaction journal on the next pass without overwriting subsequent edits.
- Register the `DigitalHouses` panel at `/digital-houses/` and publish its views from local YAML through HA Core WebSocket without a restart. Back up previous managed panel configurations in private `/data`.
- Automatically configure `homeassistant.packages: !include_dir_merge_named packages/` in `configuration.yaml` if not present; preserve custom settings and previous packages, using a backup transaction.
- Request one HA quick YAML reload when packages change. Reloadable integrations apply without restart; integrations requiring startup will activate after a regular HA restart. DH Sync does not restart HA.

**GitHub is the source of truth for published YAML.** Changes are automatically installed; backups allow recovery. Resources removed from GitHub are not automatically deleted from Home Assistant.

DH Sync registers and maintains its own `DigitalHouses` Storage dashboard via the official Home Assistant WebSocket API using its Supervisor token. Local YAML stays canonical; other dashboards and `.storage` files are never edited directly. **It does not restart Home Assistant:** dashboard view changes are applied to the managed Storage panel over the WebSocket API; new integrations in packages may require a regular HA restart to become active. The app status screen makes no claim to have reloaded HA.

The only product-source admission rule is GitHub owner `DigitalHouses`. Safe Git paths, YAML identity and duplicate detection are operational file-integrity checks, not additional product/version gates.

Currently published canonical packages:
- `digitalhouses_pve_agent/packages/common/dh_pve_agent_package.yaml`
- `digitalhouses_plex_agent/packages/common/dh_plex_app_package.yaml`

Site-specific notification variants stay locally managed until a single portable canonical resource exists; no custom notification scripts are replaced from undocumented examples.

## Rollout

Installing DH Sync 0.4.4 enables automatic synchronization of published resources. Its Ingress panel shows last scan, updated/current counts, skipped conflicts and resource status. The old 0.3.x manual Apply/Rollback flow is no longer used by the running app.

Tests: `python -m unittest discover -s digitalhouses_sync_app/tests -p 'test_*.py'`, plus repository CI.
