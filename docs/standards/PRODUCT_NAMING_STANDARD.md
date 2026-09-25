# DigitalHouses Product Naming Standard

**Status:** Approved  
**Date:** 2026-09-26  
**Scope:** All Apps and Agents in `DigitalHouses/home-assistant-apps`

## 1. Core rule

Every DigitalHouses product has one canonical machine-readable product identifier:

```text
digitalhouses_<function>_<type>
```

The three parts are mandatory:

- `digitalhouses` — repository/product namespace;
- `<function>` — the product function in lowercase `snake_case`;
- `<type>` — exactly `app` or `agent`.

Examples:

```text
digitalhouses_internet_app
digitalhouses_recorder_app
digitalhouses_backblaze_app
digitalhouses_pve_agent
digitalhouses_plex_agent
```

Do not introduce alternate word order, abbreviated product identity, or role synonyms such as:

```text
dh_pve_app
dh_app_pve
digitalhouses_plex_monitoring
digitalhouses_db_monitoring
digitalhouses_backblaze
```

Historical identifiers may remain in immutable history or temporarily in compatibility-sensitive runtime surfaces during an explicit migration. They are not valid naming patterns for new code.

## 2. Canonical product identity

The canonical identifier must be the same identity used by all repository-level product contracts:

```text
product registry
release identifier
Git tag prefix
telemetry product
container/image product name
repository documentation
repository directory
Home Assistant App slug after its compatibility migration
```

A product-specific implementation must not invent a second product name for one of these surfaces.

The canonical product identifier is stored as `id` in:

```text
digitalhouses-stats/digitalhouses_stats/product_registry.json
```

That registry is the machine-readable source of truth for product identity.

## 3. Product type

The product registry declares:

```json
"type": "app"
```

or:

```json
"type": "agent"
```

The declared type must match the final component of the canonical product identifier:

```text
digitalhouses_<function>_app   -> app
digitalhouses_<function>_agent -> agent
```

Repository implementation type remains:

```text
app   -> haos_addon
agent -> linux_agent
```

The two concepts are related but not interchangeable: `app/agent` is public product naming; `haos_addon/linux_agent` is the runtime/application-type contract.

## 4. Home Assistant entity namespace

Home Assistant entity IDs use a compact product prefix:

```text
dh_<function>_<type>
```

For example:

```text
digitalhouses_internet_app  -> dh_internet_app
digitalhouses_recorder_app  -> dh_recorder_app
digitalhouses_backblaze_app -> dh_backblaze_app
digitalhouses_pve_agent     -> dh_pve_agent
digitalhouses_plex_agent    -> dh_plex_agent
```

Every product-owned Home Assistant entity ID is then:

```text
<domain>.dh_<function>_<type>_<entity>
```

Examples:

```text
sensor.dh_internet_app_download
button.dh_internet_app_run_speedtest
sensor.dh_pve_agent_version
event.dh_pve_agent_ups_diagnostic
```

Do not reverse the order of function/type and do not add another product synonym inside the entity prefix.

The compact prefix is declared as `entity_prefix` in the product registry and must equal the deterministic shortening of the canonical identifier:

```text
digitalhouses_ -> dh_
```

## 5. Human-readable name

Public display names use:

```text
DigitalHouses <Function> App
DigitalHouses <Function> Agent
```

Examples:

```text
DigitalHouses Internet App
DigitalHouses Recorder App
DigitalHouses PVE Agent
DigitalHouses Plex Agent
```

A short UI label may omit `DigitalHouses` when screen space requires it, but this does not create another machine identity.

## 6. Repository directory and App slug

Every implemented product repository directory must equal the canonical product identifier:

```text
digitalhouses_<function>_<type>/
```

The product registry field `repository_directory` is authoritative and, for an implemented product, must equal `id`.

For Home Assistant Apps the registry also declares the current installed identity as `haos_slug`.

For a new App:

```text
haos_slug == id
config.yaml slug == id
```

A released App whose existing Supervisor identity uses a legacy slug may retain that slug only as an explicit compatibility exception. The registry must then record both the current `haos_slug` and a controlled migration target to the canonical ID. A repository-directory rename alone is not evidence that Supervisor can transparently remap an installed App, its options, `/data`, or backup/restore identity.

After the product-specific controlled migration is completed:

```text
haos_slug == id
config.yaml slug == id
```

and the pending migration marker must be removed. Repository validation must prevent regression.

Linux service names, filesystem paths, MQTT identities and released Home Assistant entity IDs are independent compatibility-sensitive runtime surfaces. A structural repository rename must not silently rename them.

## 7. MQTT and internal constants

MQTT Discovery entities exposed to Home Assistant use the compact `dh_<function>_<type>` entity namespace.

Product-level constants in code should use the canonical identity explicitly, for example:

```text
PRODUCT_ID = "digitalhouses_internet_app"
ENTITY_PREFIX = "dh_internet_app"
```

Do not derive product identity from a repository directory that is still carrying a legacy name.

## 8. Releases, telemetry and container images

Release and telemetry identity must use the canonical product identifier exactly.

For a product version `1.2.3`:

```text
product: digitalhouses_internet_app
tag:     digitalhouses_internet_app-v1.2.3
```

Telemetry allowlists, payloads, release tooling, registry entries and documentation must use the same product identifier.

For Home Assistant Apps, the GHCR repository name is derived directly from the canonical ID without an alternate dashed product alias:

```text
ghcr.io/digitalhouses/<canonical_product_id>
```

Example:

```text
ghcr.io/digitalhouses/digitalhouses_recorder_app:0.1.9
```

Underscores are retained. Tooling must generate the image repository mechanically from the registry ID; a second machine-readable product name must not be stored merely for registry formatting.

Historical release tags are immutable and are never renamed.

## 9. Current canonical names

| Product | Canonical ID | Type | HA entity prefix |
| --- | --- | --- | --- |
| DigitalHouses PVE Agent | `digitalhouses_pve_agent` | `agent` | `dh_pve_agent` |
| DigitalHouses Plex Agent | `digitalhouses_plex_agent` | `agent` | `dh_plex_agent` |
| DigitalHouses Recorder App | `digitalhouses_recorder_app` | `app` | `dh_recorder_app` |
| DigitalHouses Speedtest App | `digitalhouses_speedtest_app` | `app` | `dh_speedtest_app` |
| DigitalHouses Backblaze App | `digitalhouses_backblaze_app` | `app` | `dh_backblaze_app` |
| DigitalHouses Internet App | `digitalhouses_internet_app` | `app` | `dh_internet_app` |
| DigitalHouses Climate App | `digitalhouses_climate_app` | `app` | `dh_climate_app` |

The Speedtest App and Internet App remain distinct product identities. A replacement product does not reuse the historical identity of another product.

## 10. Migration rule

Legacy naming is migration debt, not a second supported convention.

Repository-structure migration and installed-runtime migration are deliberately separate when runtime compatibility is at risk.

The repository-structure migration updates together:

- canonical repository directories;
- product registry identity/directory mappings;
- repository discovery and validator dispatch;
- CI source paths;
- release tooling source paths;
- active documentation links.

It does not by itself rename installed compatibility interfaces.

A later product-specific runtime migration may update, as applicable:

- Home Assistant App slug;
- Linux service and filesystem paths;
- MQTT topics/device identifiers/unique IDs;
- Home Assistant entity IDs;
- package and dashboard examples that depend on those IDs;
- persistent state layout.

Compatibility-sensitive renames require product-specific release notes, migration/rollback procedures and tests.

Do not rewrite historical tags, historical changelog entries, or old engineering records merely for cosmetic consistency.

## 11. Repository validation

Repository CI must validate at least:

1. every product registry `id` matches `digitalhouses_<function>_<app|agent>`;
2. registry `type` matches the identifier suffix;
3. registry `entity_prefix` equals the deterministic `digitalhouses_ -> dh_` shortening;
4. every implemented `repository_directory == id`;
5. every registry implementation directory exists and every implementation marker belongs to the registry;
6. validator dispatch is keyed by canonical registry `id`;
7. every registered implementation has common, type-specific and product-specific validation;
8. release identifiers and telemetry product identity are the registry `id`;
9. every Home Assistant App `config.yaml slug` equals registry `haos_slug`;
10. a legacy App slug is accepted only with an explicit controlled migration marker to the canonical ID;
11. a completed App slug migration cannot regress to a legacy slug.

If code, documentation and this standard disagree, the mismatch is a repository defect.
