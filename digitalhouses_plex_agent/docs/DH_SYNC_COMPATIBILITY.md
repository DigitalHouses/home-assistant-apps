# Plex Agent — DH Sync 0.4.0 automatic resources

**Normative source:** [DH Sync Resources Standard](../../docs/standards/DH_SYNC_RESOURCES_STANDARD.md)
and [DH Sync Discovery Contract v1](../../digitalhouses_sync_app/docs/DH_SYNC_DISCOVERY_CONTRACT_V1.md).
The old opt-in / pinned SHA / agent-version compatibility-gate workflow
has been superseded. This is product-owned resource documentation, not an
alternative DH Sync standard.

## Product identity and MQTT

- Registry product: `digitalhouses_plex_agent`; `type: agent`.
- Repository: `https://github.com/DigitalHouses/home-assistant-apps`;
  `product_path: digitalhouses_plex_agent`.
- Default instance `plex` publishes retained QoS1 source metadata at
  `DigitalHouses/Global/digitalhouses_plex_agent/sync`.
- Non-default instance `plex_guest` publishes at
  `DigitalHouses/Global/digitalhouses_plex_agent/plex_guest/sync`.
- Version is the running `BuildInfo.version` loaded from installed
  `VERSION` / `BUILD_INFO`, not the view or package revision.
- MQTT source uses six fields: `schema` = 1, `product_id`, `type`,
  `version`, `repository` and `product_path`. The repository is a source
  claim and **does not authorize installation of executable product code**.

The product's existing retained availability remains
`DigitalHouses/Global/digitalhouses_plex_agent/availability` for the default
instance. Its LWT sends `offline` and MQTT Discovery remains
`homeassistant/device/digitalhouses_plex_agent_plex/config`. Custom
instances keep their existing availability suffix and Discovery identity.
The existing MQTT_PAUSED reconnect/backoff behavior and HA diagnostic
entities `sensor.dh_plex_agent_version` /
`sensor.dh_plex_agent_started_at` remain unchanged. Offline is not uninstall.

DH Sync admits **any structurally valid HTTPS GitHub repository owned by
DigitalHouses**. The MQTT topic provides identity; metadata version and
product_path are not approval gates. The app resolves the remote default
branch to a consistent Git SHA and fetches product resource files from
that snapshot.

## Files published for automatic delivery

| Category | Source | Existing identity |
| --- | --- | --- |
| Russian view | `dashboards/ru/10_plex.yaml` | `path: dh-plex-agent` |
| Common Recorder | `packages/common/dh_plex_app_package.yaml` | `dh_app_plex_monitoring_package` |
| RU notification package | none published | no portable recipient-free YAML yet |
| English view/package | none published | DH Sync 0.4.0 currently uses RU only |

The canonical view is a standalone `type: sections` Lovelace view with four
sections. It is byte-identical to the operator-approved source at
`examples/lovelace/plex-dashboard.yaml` once the three comment header
lines and blank separator are excluded. The Recorder package likewise
matches the historical `examples/packages/dh_plex_app_package.yaml` body,
with 24 recorded and six excluded entity IDs. Those `examples/` paths are
**not** automatically installed by DH Sync.

The `DH-View-Version` / `DH-Package-Version` comments are retained only
as descriptive metadata (1.0.0). No `DH-Compatible-Agent` range applies,
and the installed Plex Agent version **does not gate** discovery or YAML
sync. Published files can be updated by simply changing their content and
merging the reviewed PR to `main`. After merging, installations may receive
a changed YAML file automatically without a second product release.

### What DH Sync 0.4.0 changes on HA

- Reads `dashboards/ru/*.yaml`, `packages/common/*.yaml` and
  `packages/locales/ru/*.yaml` inside the announced product folder.
- Finds views by Lovelace `path` and packages by their top-level YAML key.
- Writes standalone views to `/config/dashboards/dh/views/`.
- Finds and updates any existing Recorder package **at its current location**
  under `/config/packages/`, preserving its package key. A new package would
  be written to `/config/packages/dh/`.
- Makes a backup before changed-file replacement; restores failed or
  interrupted transactions when safe, avoids duplicate keys/path conflicts.
- Never modifies `.storage`, automatically deletes missing resources,
  updates the Plex binary or restarts Home Assistant.

**Existing Storage dashboard limitation:** the original Plex view on HOME
is inside `/config/.storage/lovelace.dashboard_system` with
`path: dh-plex-agent`. DH Sync detects this as a Storage path collision
and skips this YAML view. This is deliberate, not successful migration.
To move that user-managed view, use a separately supported Storage migration
procedure; the product **must not** modify that Storage dashboard.

DH Sync does not automatically install HACS frontend dependencies. The
current view uses Mushroom, `auto-entities`, `button-card` and
`entity-progress-card-template`.

## Historical HOME/CORE validation — not a version gate

On 2026-11-14 the operator compared the full original HOME Storage Plex
view to the canonical source. Normalized SHA-256 matched:
`9a1f922f58bcdcc2fc285c9f262f57ab9aed22a3487899d8cf64fe2d5bbb48b8`.
The HOME Recorder at
`/config/packages/DH/dh_plex_app_package.yaml` had SHA-256
`340cce8e68477b2faf2192f50465471e18c7e9311b46930620a4c01b7e62ff4a`.
These are installed-source baselines; the canonical files with metadata
comment headers have different byte hashes.

Plex Agent v0.8.17 passed live MQTT/Plex and CPU self-diagnostic checks on
HOME. On CORE Media VM 192.168.11.243 the user upgraded to released 0.8.18,
with MQTT CONNECTED to 192.168.11.242:1883, Plex API OK and successful
QoS1 publication. Later a CORE operator check reported Plex visible and
the retained `/sync` entry Online. This is evidence of the existing view,
not proof that DH Sync updated or migrated any HA YAML.

The existing GPU machine event entity remains
`event.dh_plex_agent_gpu_diagnostic` and agent CPU events use
`event.dh_plex_agent_cpu_diagnostic`. Notification routing stays local;
there is no portable RU notification package in the canonical directory,
so no notification file is automatically installed by DH Sync.

## Test and release policy

Product tests ensure the exact approved YAML bodies, standalone view,
stable `path`, Recorder key and entity list, no duplicate canonical names
and the six-field retained MQTT source payload. Run:

- `PYTHONPATH=digitalhouses_plex_agent python -m pytest digitalhouses_plex_agent/tests -q`
- `python scripts/validate_repository.py`

**Important:** a change to an already published canonical YAML is live
distribution intent. Verify its contents and effects **before merging**
the PR because DH Sync may update enabled HA files on its next sync. A
documentation/test-only PR is not a YAML update and does not require
incrementing Plex Agent `VERSION` or changing its installed code.
