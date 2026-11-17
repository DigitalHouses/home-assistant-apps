# DH Sync 0.6.0 — Current architecture

Authoritative standard: [DH Sync Resources Standard](../../docs/standards/DH_SYNC_RESOURCES_STANDARD.md).

- Product registry: broker retained MQTT `/sync` only, rebuilt on reconnection.
- Source admission: GitHub repository owner `DigitalHouses` only.
- Panel catalog: `digitalhouses_sync_app/dashboards/*.yaml` on GitHub.
- Product Views: `<product_path>/dashboards/ru/*.yaml` on GitHub.
- Product Packages: `<product_path>/packages/common/*.yaml` and `packages/locales/ru/*.yaml`.
- Panel YAML determines native Dashboard fields and ordered, reusable View references. MQTT `dashboard` is ignored.
- Publish through HA's supported Lovelace Storage WebSocket API; no direct `.storage` edits or local View YAML copies.
- Packages are synchronized atomically with backups under `/data/dh-sync-auto/`; do not update other Apps/Agents or restart HA.
- No migration, old panel adoption, product-version gates or manual confirmation.

Implementation: `rootfs/app/panel_config.py`, `auto_sync.py`, `dashboard_runtime.py`, `git_source.py`.
