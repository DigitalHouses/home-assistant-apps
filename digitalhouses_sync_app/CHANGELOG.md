# Changelog

## 0.6.8

- Pin DH Journal 1.1.0 from dh-app-libraries; preserve existing SQLite history with native schema migration.
- Standard Toast notifications for meaningful sync outcomes only; shared browser preferences and RU/EN via LOG.
- One summary per sync, with confirmed View, Package and Dashboard change counts. Suppress unchanged automatic results and repeated identical failures.

## 0.6.7

- Compact full-width Ingress with manual synchronization and LOG in the header.
- In-place status updates, visible errors and confirmed resource changes; products, resource list and technical details collapsed by default.
- Count confirmed packages, individual Views and Dashboard metadata/order as separate resources, including removed Views. No extra HA API calls and no change to sync admission or restart behavior.

## 0.6.6

- Adopt shared DH Journal 1.0.3 and full-screen Ingress LOG with RU/EN, search, export and clear.
- Migrate the latest 3000 legacy SQLite records; keep original history on migration failure.
- Suppress unchanged automatic sync summaries unless debug is enabled. No sync behavior changes.

## 0.6.5

- Persistent local SQLite operational journal in admin Ingress with product/event filters, JSONL export and explicit clear.
- Configurable retention (30 days / 10,000 rows / 100 displayed by default), enforced on write/read and at startup; no external database.
- Logs lifecycle, MQTT registry changes, sync runs, package transactions, panel/view updates and errors without changing sync eligibility or HA restart policy.

## 0.6.4

- Emergency rollback of the unauthorized cross-project changes introduced in v0.6.3 (PR #608).
- Restores the exact DH Sync v0.6.2 runtime, automatic YAML synchronization and reload-only behavior.
- No Recorder Core restart feature, no new permissions, no change to PBS Agent, dashboards or backup jobs.
- New release number is required because a previous immutable v0.6.2 tag already exists; v0.6.4 is the deployable rollback.

## 0.6.2

- Implement DH Sync telemetry using shared protocol v1 / policy v2 with explicit HA App consent.
- Add persistent per-installation UUIDv4 and 256-bit token in `/data`, 24-hour jittered reporting and one-hour failure backoff.
- Include authenticated installation/history erasure and local credential rotation; isolate telemetry network errors from dashboard synchronization.
- Register only DH Sync's product identifier in the shared Stats allowlist and update DH Sync validation; no changes to other product runtime.
- **Activation required:** `telemetry_enabled` defaults false. After upgrading, explicit acceptance (`true`) is required before the App starts; operators must plan this for auto-updated installations. Legal/privacy assessment of mandatory public deployment remains a separate obligation.


## 0.6.1

- Restore the agreed **«Проверить и обновить»** button in DH Sync admin Ingress.
- One click forces fresh GitHub revisions (bypassing the 5-minute snapshot cache), runs the existing automated Dashboard and Packages synchronization immediately, and reports the result.
- No separate preview, Apply confirmation, version gate or change to any other App/Agent. The hourly and MQTT-triggered synchronization continue.


## 0.6.0

- Declarative GitHub panels in `digitalhouses_sync_app/dashboards/*.yaml`, ordered Views and native HA title/icon/sidebar/admin properties.
- One canonical product View can be displayed in multiple panels. A product is discovered only from retained MQTT `/sync`.
- Ignore all old MQTT `dashboard` routing; no legacy panel or view migrations.
- Publish Views directly to Lovelace Storage via the supported WebSocket API; continue safe automatic package synchronization.
- Single [DH Sync Developer Standard](../docs/standards/DH_SYNC_DEVELOPER_STANDARD.md) for App/Agent MQTT, canonical Views and Packages; obsolete standalone Sync contracts removed.
- Tests for reusable Views, ordering, admin access, idempotence and absent products.

## 0.5.1

- MQTT retained `DigitalHouses/Global/+/sync` and `+/+/sync` are the sole product registry: no disk-loaded `product_sources.json` and no local product discovery fallback.
- Build a fresh in-memory registry from each broker subscription; handle empty retained MQTT tombstones. Products are accepted by their topic and DigitalHouses-owned GitHub repository, regardless of `availability`, reported version or product name.
- Stop subscribing to or displaying product `availability`. The product list reflects only MQTT `/sync`; version is informational.
- Skip dashboard/package publication when the MQTT registry is empty. Preserve existing installed resources, without inventing products from old YAML.

## 0.5.0

- Use the optional retained MQTT `/sync.dashboard` slug to route each product's canonical YAML views to a named Home Assistant panel (e.g. `dh-system`, `dh-climate`).
- Create named dashboard panels automatically through HA's supported WebSocket API, with per-panel ownership markers and backups. Products without the field retain `digital-houses`.
- Migrate only DH Sync-owned views from the legacy panel after their new destination has been saved; preserve manually added views, user dashboards and package behavior.
- Deduplicate multi-instance source announcements: explicit routing wins over legacy announcements, while conflicting explicit routes are reported.
- Display each panel, view count and update status in the Ingress catalog.

## 0.4.4

- Automatically configure `homeassistant.packages: !include_dir_merge_named packages/` when canonical packages are published and the loader is missing.
- Preserve existing configuration.yaml formatting and unrelated packages; safely reject conflicting loaders instead of overwriting them.
- Back up and atomically update configuration.yaml through the existing transaction journal; reuse prior paths by package identity.
- Request one Home Assistant quick YAML reload after changed packages without restarting HA. Report installation and reload state separately; newly added integrations can still require a normal HA restart.

## 0.4.3

- Register a visible DigitalHouses panel using the supported Home Assistant Lovelace WebSocket API. Previous file-only sync did not register a panel.
- Display canonical YAML views in the panel without restarting HA, and preserve unrelated dashboards and user-only views.
- Use the Supervisor Core API proxy with private backup and an ownership marker; never edit .storage directly.
- Report panel errors in DH Sync rather than reporting OK for files only.

## 0.4.2

- Fix a false Lovelace view collision when a Storage dashboard in a different URL namespace uses the same view path as DigitalHouses YAML.
- Limit automatic synchronization's view identity checks to the DigitalHouses YAML views directory. Do not inspect or change unrelated .storage dashboards.
- Keep existing local YAML path/filename conflict protection; add tests for same-name Storage views and inaccessible unrelated Storage state.

## 0.4.1

- Automatically create missing /config/dashboards/dh/views and /config/packages/dh directories on first sync.
- Create the minimal DigitalHouses parent ui.yaml only when absent; retain existing files and fail on occupied or unsafe paths.
- Synchronize published dashboard and package YAML on a fresh HA installation without manual mkdir, confirmation or HA restart.

## 0.4.0

- Enable zero-click automatic dashboard and Home Assistant package sync after MQTT discovery and hourly.
- Share free public Git snapshots across products, without GitHub REST API, tokens or product-version gates.
- Reuse YAML identity for installation: Lovelace path for views and top-level package key for packages. Keep existing local filenames.
- Back up changed files in persistent /data and atomically replace them; recover interrupted transactions. Never overwrite ambiguous duplicate keys/paths or Lovelace Storage views.
- Publish existing PVE base package as a canonical resource, alongside the existing Plex package.
- Replace the running manual Apply/confirmation UI with a minimal status panel. No automatic Home Assistant restart, entity or package registration, .storage changes or agent updates.


## 0.3.1

- Replace per-product unauthenticated GitHub REST API metadata, branch and directory requests with free, public shallow Git transport. No token, GitHub App or paid plan.
- Clone a single immutable default-branch snapshot per distinct repository and cache it for five minutes; enumerate and read canonical dashboard YAML from local Git objects. No REST rate-limit dependency.
- Keep owner `DigitalHouses` as the sole source admission rule, regardless of product, repo or Agent/App version. Missing optional directories remain normal.
- Add local Git transport tests for SHA pinning, repo sharing, expiry, unknown products and unsafe origins/paths; preserve manual Apply, backup and Rollback behavior.


## 0.3.0

- Add operator-initiated owner-only GitHub YAML Apply for discovered products, without product, agent-version or compatibility allowlists.
- Exact pinned commit and source SHA in preview; reject changed local bytes, duplicate paths and Lovelace Storage conflicts before writing.
- Back up replaced YAML bytes to private persistent /data transaction journal; atomic per-file replacements and explicit rollback, refusing to override newer user edits.
- Expose per-product preparation, confirmation and rollback in admin-only Supervisor Ingress; POST requires a single-use preview token and an explicit checkbox. No automatic reload, HA API access, .storage writes, packages, agent actions or background updates.
- Writable HAOS config bind is required only for manual view file Apply; no other HA file modifications.
- Treat a product without dashboards/ru directory as no published resources rather than GitHub directory error.


## 0.2.2

- Remove DH-Compatible-Agent/App headers from canonical PVE, UPS, Plex and Recorder dashboards; no compatibility declaration is required.
- Remove legacy compatibility text, range display, `constraint` and unreachable version-block status from the read-only DH Sync preview and CORE audit.
- Keep GitHub owner `DigitalHouses` as the only source-admission rule, while retaining safe parsing, read-only access and manual review before any future Apply.
- Update tests and product documentation to remove version-range and product-registry admission assumptions.

## 0.2.1

- Reduce source admission to the GitHub repository owner DigitalHouses. Remove the fixed monorepo check, product-specific SHA allowlist, product-path equality rule, agent/app version gates and required DH-Compatible metadata.
- Resolve each GitHub repository's default branch to a commit SHA on explicit user request. Discover dashboards/ru/*.yaml from that SHA; support Recorder and future products without central registration.
- Keep dashboard metadata as optional informational text. The local CORE diff works across DigitalHouses repositories and safe relative product paths.
- Retain technical URL/path parsing to prevent malformed network requests and retain read-only HAOS access; no Apply, automatic YAML writes, updates or restarts.

## 0.2.0

- Add operator-triggered read-only CORE HAOS YAML audit through Supervisor homeassistant_config map with read_only: true.
- Compare pinned PVE Proxmox/UPS and Plex resources against local DigitalHouses views by Lovelace path, exact SHA-256 and parsed YAML. Present a bounded, HTML-escaped diff of modified view YAML.
- Detect absent views, occupied filenames, duplicate YAML paths and matching Lovelace Storage views including modern .storage/lovelace.<dashboard> variants, without exposing Storage JSON.
- Default Ingress never scans local files; GitHub preview and local audit require distinct GET actions. HTTP POST still returns 405.
- Fail closed for missing or writable mount, symlink, unreadable/malformed or oversized files, and source identity mismatch.
- No HA Core API, writable HA mount, backup, Apply, rollback, Recorder mutation or automatic restart in v0.2.0.

## 0.1.4

- Pin the immutable approved merged PR #502 commit for both PVE Proxmox/UPS views and merged PR #508 for Plex Dashboard; do not fetch unreviewed Draft sources.
- Confirm compatibility preview for PVE Agent 0.5.89 (>=0.5.88,<0.5.90) and Plex Agent 0.8.18 (>=0.8.17,<0.8.19), while future versions still fail closed.
- Improve GitHub resource table column widths and natural word wrapping for longer Russian names.
- Retain GET-only, admin-only preview with no Home Assistant API/config mount, file comparison, Apply, backup, rollback, automatic agent updates or YAML writes.

## 0.1.3

- Add operator-initiated, read-only preview of canonical RU dashboards at immutable pinned GitHub commits.
- Discover any number of YAML views under each allowed product's `dashboards/ru/`, including both PVE views and the Plex view, without embedding YAML filenames in MQTT.
- Display view revision, compatibility range, source review state and blocked reasons for running Agent 0.5.89/0.8.18.
- Validate standalone YAML, duplicate paths and GitHub response origins. Do not introduce HA API access, config mount, YAML Apply or background polling.
- Add HAOS container smoke coverage and unit tests for GitHub listing, version gates and read-only Ingress.

## 0.1.2

- Show the installed release version in the Ingress heading and startup log using APP_VERSION instead of hardcoding v0.1.0.
- Recognize the Sync App's own canonical product-level availability topic and display Online after receiving its retained MQTT status.
- Add regression tests for release-version rendering, escaped header output, and self availability; no change to YAML, HA API permissions, or MQTT Discovery Contract v1.

## 0.1.1

- Fix HAOS startup crash with Alpine `py3-paho-mqtt` 1.x, where `mqtt.CallbackAPIVersion` is not available.
- Use Paho 2.x callback API when present and a compatible 1.x client otherwise; accept both four- and five-argument connect callbacks.
- Add unit regression tests for both Paho API generations and a smoke test that executes the MQTT client constructor inside the actual built HAOS image.
- No changes to broker authentication, MQTT topic names, Dashboard YAML, HA permissions or read-only Ingress behavior.

## 0.1.0

- First HAOS Ingress read-only catalog of detected DigitalHouses agents and apps.
- Discover product ID, running version, instance and owning GitHub repository from retained MQTT Discovery Contract v1 messages.
- Strictly accept only direct GitHub repositories owned by `DigitalHouses`; reject URL spoofing and mismatched product identities.
- Display product-level online/offline/unknown availability separately from retained source metadata. Offline never means uninstall.
- Publish its own Version/Started-at diagnostics and source metadata using the existing HAOS MQTT service.
- No Home Assistant API permission, configuration mount, YAML Apply or Rollback, external services, dynamic downloads, Home Assistant restarts or executable agent updates in installed v0.1.0.
- Keep view transaction and migration prototypes in source for future product-compatibility-gated integration; they are not part of the running v0.1.0 UI.

## 0.0.1 — unpublished prototype

- MQTT product inventory and diagnostics.
- Read-only Plex adoption preflight and separately gated Storage migration prototype.
