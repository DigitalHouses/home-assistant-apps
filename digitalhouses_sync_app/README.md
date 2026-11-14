# DigitalHouses Sync App — 0.4.1

DH Sync automatically maintains Home Assistant dashboards and packages from public GitHub repositories owned by **DigitalHouses**. No prompts, buttons, token, paid plan, product allowlist or app-version checks.

## How it works

- On MQTT discovery and every hour, read a shared shallow public Git snapshot.
- Find canonical `dashboards/ru/*.yaml`, `packages/common/*.yaml`, and `packages/locales/ru/*.yaml` for every discovered product.
- Find local views by their Lovelace `path` and packages by their top-level YAML key. Preserve existing local filenames/paths.
- When bytes differ, save the original in private persistent `/data/dh-sync-auto/`, then replace the YAML atomically. No user confirmation.
- Retain other files untouched. Reject ambiguous duplicate paths/keys and Lovelace Storage conflicts rather than guessing. Missing resources are normal.
- If interrupted mid-write, restore from the transaction journal on the next pass without overwriting subsequent edits.

**GitHub is the source of truth for published YAML.** Changes are automatically installed; backups allow recovery. Resources removed from GitHub are not automatically deleted from Home Assistant.

DH Sync never changes `.storage`, product binaries, HA credentials or MQTT configurations. **It does not restart Home Assistant:** dashboard file changes are visible when YAML views are re-read; Home Assistant package changes may require a normal HA restart before they become active. The app status screen makes no claim to have reloaded HA.

The only product-source admission rule is GitHub owner `DigitalHouses`. Safe Git paths, YAML identity and duplicate detection are operational file-integrity checks, not additional product/version gates.

Published canonical package examples:
- `digitalhouses_pve_agent/packages/common/dh_pve_agent_package.yaml`
- `digitalhouses_plex_agent/packages/common/dh_plex_app_package.yaml`

Site-specific notification variants stay locally managed until a single portable canonical resource exists; no custom notification scripts are replaced from undocumented examples.

## Rollout

Installing DH Sync 0.4.0 enables automatic synchronization of published resources. Its Ingress panel shows last scan, updated/current counts, skipped conflicts and resource status. The old 0.3.x manual Apply/Rollback flow is no longer used by the running app.

Tests: `python -m unittest discover -s digitalhouses_sync_app/tests -p 'test_*.py'`, plus repository CI.

The Ingress status groups **Dashboards** and **Packages** separately, showing each discovered resource's name, exact local `/config/` path and last synchronization outcome. `examples/` is never scanned as a canonical source.
