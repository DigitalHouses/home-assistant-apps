# DigitalHouses Recorder App — DH Sync 0.4 integration

**Current standard:** [DH Sync Resources Standard](../../docs/standards/DH_SYNC_RESOURCES_STANDARD.md).
DH Sync 0.4 automatically maintains canonical GitHub YAML. This document
supersedes Recorder's earlier pinned-commit, version-range, Preview/Apply and
manual-acceptance procedure. The **only source admission rule** is a public
GitHub repository whose owner is `DigitalHouses`.

## Product MQTT source — existing producer remains unchanged

The Recorder App uses its existing MQTT client to publish retained QoS 1 JSON
at every successful connect or reconnect:

```text
DigitalHouses/Global/digitalhouses_recorder_app/sync
```

Example, with the version taken from the running App:

```json
{
  "schema": 1,
  "product_id": "digitalhouses_recorder_app",
  "type": "app",
  "version": "0.1.29",
  "repository": "https://github.com/DigitalHouses/home-assistant-apps",
  "product_path": "digitalhouses_recorder_app"
}
```

The repository and path are product-owned constants. DH Sync takes product
identity from the MQTT topic, validates the GitHub owner, and uses the path
to locate published resources. Product version, schema, type and path do
**not** form additional *source admission* or dashboard compatibility gates.
There is no pin registry, version-range marker, REST API token, or manual
release-registration step. GitHub's default branch is the YAML source of truth.

The existing retained/LWT availability topic is
`DigitalHouses/Global/digitalhouses_recorder_app/availability`; it is separate
from the `/sync` source metadata and subsystem availability. Retained `/sync`
does not prove that an App instance is currently online and does not authorize
deleting resources. No heartbeat, new MQTT client, or polling loop is added.

Recorder's HA MQTT Discovery, entities, database/storage monitoring, update
controls and optional telemetry consent are unchanged.

## Published Recorder resource

| Property | Value |
| --- | --- |
| Repository | `DigitalHouses/home-assistant-apps` |
| Product path | `digitalhouses_recorder_app` |
| Canonical source | `dashboards/ru/10_recorder.yaml` |
| Lovelace kind | One standalone `sections` view |
| Stable view identity | `path: recorder` |
| Optional informational header | `DH-View: dh_recorder_app`, `DH-View-Version: 1.0.0` |
| Canonical packages | None |
| Other locales | Not published; DH Sync 0.4 only synchronizes Russian |

The source contains the original maintained Recorder dashboard from
`examples/lovelace/dh_recorder_app_dashboard.yaml`, with informative comments
at the top. After removing that comment header, the Lovelace body is
byte-for-byte identical to the maintained example (original Git blob
`45dd279a425c0165deccdb0b53e6d9fe6b37a8af`). No card, graph, control,
entity, view title or `path` has been altered for the DH Sync transition.

There is deliberately no `DH-Compatible-App` or `DH-Compatible-Agent` range.
App version and `DH-View-Version` are informative and must not restrict the
automatic Sync 0.4 resource fetch. No empty `packages/common` or
`packages/locales/ru` files are created. Files under `examples/` never
become DH Sync resources.

## Automatic installation and existing local files

1. DH Sync discovers the Recorder MQTT `/sync` source and periodically
   rechecks its owned GitHub repository.
2. It reads `digitalhouses_recorder_app/dashboards/ru/10_recorder.yaml` at
   one Git revision from the default branch.
3. It identifies a local YAML view under `/config/dashboards/dh/views/`
   by Lovelace `path: recorder`, preserving the local filename when present.
4. **If bytes differ, it backs up the original and atomically replaces the
   YAML automatically. No Preview, Apply button, confirmation or compatible
   App-version check is involved.** Backup/journal state is maintained by DH
   Sync under private persistent `/data/dh-sync-auto/`.
5. It skips ambiguous duplicate paths, occupied filenames and Lovelace Storage
   conflicts instead of guessing. It never edits `.storage`, deletes YAML
   merely because a GitHub resource disappears, or restarts Home Assistant.

**Operational consequence:** A locally customized file with the same
`path: recorder` can be replaced by published GitHub YAML when DH Sync 0.4
runs. Retained backups provide recovery, but the App's GitHub canonical file
is authoritative. Review and test canonical YAML **before merging to main**
because the next Sync scan can distribute it automatically.

The dashboard requires frontend resources installed independently in HA:
Mushroom, **button-card >= 5.0** (for `update_timer`),
**mini-graph-card**, and **entity-progress-card**
(`custom:entity-progress-card-template`). DH Sync does not install HACS
cards. Missing cards affect rendering but do not change the source-admission
rule. The Supervisor-provided
`update.digitalhouses_recorder_app_update` is not an MQTT entity published
by Recorder; `button.press` and `update.install` are action names.

## Validation

```bash
python -m unittest discover -s digitalhouses_recorder_app/tests -p 'test_*.py'
PYTHONPATH=digitalhouses_sync_app/rootfs/app python -m unittest discover -s digitalhouses_sync_app/tests -p 'test_auto_sync.py'
PYTHONPATH=digitalhouses_sync_app/rootfs/app python -m unittest discover -s digitalhouses_sync_app/tests -p 'test_discovery_contract.py'
python scripts/validate_repository.py
```

Recorder regression tests protect the canonical standalone Lovelace path, exact
view body, source ownership, MQTT identities, existing controls, entity
references and frontend dependencies. DH Sync's focused auto-sync and discovery tests cover owned-repository
admission, local identity matching, backups, atomic writes and conflict
handling. The complete DH Sync suite additionally requires the Sync App's
runtime dependencies (including paho-mqtt) and is run by repository CI. CI validates the source; live HACS/frontend rendering is
not inferred from unit tests and is not a DH Sync admission gate.

**No new Recorder App release is needed for this source-only correction.**
The existing Recorder 0.1.29 runtime and its retained `/sync` producer are
already compatible with the DH Sync 0.4 source contract.
