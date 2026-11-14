# DigitalHouses Sync App — v0.3.1

## One rule: GitHub owner DigitalHouses

DH Sync discovers products from retained MQTT /sync messages and reads dashboard YAML from their GitHub repositories. **The only source-admission rule is that the GitHub repository owner is DigitalHouses.**

No hardcoded approved product list, no static per-product Git SHA pins, no fixed monorepo, no product_path equality gate, and no required Agent/App version range or DH-Compatible header.

Each explicit GitHub preview resolves the repository's default branch to a concrete SHA and reads every dashboards/ru/*.yaml from that single revision. This supports PVE (Proxmox plus UPS), Plex, Recorder, and future DigitalHouses products. View revision metadata may be shown for information; compatibility ranges are neither read nor displayed.

The separate 'Сравнить с файлами CORE' action compares actual YAML views with GitHub by Lovelace path, SHA-256 and parsed YAML. It reports changes, missing files, duplicate paths and Storage collisions without modifying them.

## Free public Git transport (0.3.1)

DH Sync **does not call the GitHub REST API** for discovery, dashboard listing or YAML download. It does not require a PAT, GitHub App, account sign-in or paid GitHub plan.

For each distinct public repository under `DigitalHouses`, the add-on uses `git clone --depth=1 --single-branch --no-checkout` once, caches that immutable Git commit for five minutes, enumerates product views with `git ls-tree` and reads exact file blobs locally using `git show`. Products in the same monorepo share one snapshot. After the cache expires, the next explicit user action refreshes it. Missing resource directories are normal. GitHub may still impose general network/abuse protections; this avoids only the REST API quota, not all upstream constraints.

A plan displays the exact Git SHA of the snapshot used for Apply, and records source bytes before confirmation. During an accepted Apply, no GitHub access or external source re-download is necessary.

## Manual YAML Apply / Rollback (0.3.0)

The Ingress admin UI provides `Сравнить с файлами CORE` → `Подготовить Apply` for each discovered DigitalHouses product, then an explicit confirmation. It uses the exact Git commit and SHA-256 shown in preview, rejects intervening local edits and Lovelace Storage path collisions, and writes **only** `/homeassistant/dashboards/dh/views/*.yaml` as one product batch. All overwritten files are backed up in persistent private `/data/dh-sync-transactions/tx-*/`; newly created files are tracked for deletion on rollback.

The `Rollback` page restores original file bytes only if the installed YAML still matches the transaction. User edits after Apply block rollback; files outside the transaction stay untouched. No background updates, HA restart, YAML dashboard registration, .storage modifications, packages, HACS dependencies or agent binary updates. Review source and frontend prerequisites yourself before confirming.

The HAOS Home Assistant configuration bind is now writable so the app can perform the explicitly approved file replacements. All other actions remain read-only. Source admission has **one** rule: GitHub owner `DigitalHouses`. Mandatory source versions, product registries and compatibility ranges are not checked.

The `digitalhouses_sync_app` itself may have no `dashboards/ru` directory; that is shown as “Нет опубликованных ресурсов”, not an error. GitHub transport and YAML/path checks remain technical safeguards, not separate product authorization rules.

Existing storage-mode dashboards are **not** silently migrated: they must be reviewed separately. After Apply, refresh Home Assistant's dashboard in the browser and verify the view; the app never restarts HA.

See docs/DH_SYNC_DISCOVERY_CONTRACT_V1.md and docs/LOCAL_AUDIT_V2.md.
