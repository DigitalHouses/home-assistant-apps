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
repository directory after migration
Home Assistant App slug after migration
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

For every new product, the repository directory must equal the canonical product identifier:

```text
digitalhouses_<function>_<type>/
```

For every new Home Assistant App, the App slug must also equal the canonical product identifier unless the platform imposes a documented constraint.

Existing released products with a different directory, App slug, Linux service name, filesystem path, MQTT device ID, unique ID, or Home Assistant entity ID require an explicit product migration. A shared naming-policy change alone must not silently break installed systems.

After a product is migrated, its product-specific validator must prevent regression to the old name.

## 7. MQTT and internal constants

MQTT Discovery entities exposed to Home Assistant use the compact `dh_<function>_<type>` entity namespace.

Product-level constants in code should use the canonical identity explicitly, for example:

```text
PRODUCT_ID = "digitalhouses_internet_app"
ENTITY_PREFIX = "dh_internet_app"
```

Do not derive product identity from a repository directory that is still carrying a legacy name.

## 8. Releases and telemetry

Release and telemetry identity must use the canonical product identifier exactly.

For a product version `1.2.3`:

```text
product: digitalhouses_internet_app
tag:     digitalhouses_internet_app-v1.2.3
```

Telemetry allowlists, payloads, release tooling, registry entries and documentation must use the same product identifier.

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

A product migration must update all affected active surfaces together, including as applicable:

- repository directory;
- Home Assistant App slug;
- Linux service and filesystem paths;
- MQTT topics/device identifiers/unique IDs;
- Home Assistant entity IDs;
- package and dashboard examples;
- product validators and tests;
- README/DOCS/CHANGELOG;
- telemetry/release metadata.

Compatibility-sensitive renames require product-specific release notes and tests.

Do not rewrite historical tags, historical changelog entries, or old engineering records merely for cosmetic consistency.

## 11. Repository validation

Repository CI must validate at least:

1. every product registry `id` matches `digitalhouses_<function>_<app|agent>`;
2. registry `type` matches the identifier suffix;
3. registry `entity_prefix` equals `dh_<function>_<app|agent>`;
4. release-managed product identifiers remain identical to the registry `id`.

Product validators are responsible for enforcing completed runtime/entity migrations for their own product.

If code, documentation and this standard disagree, the mismatch is a repository defect.