# DH Sync v0.2.0 — read-only CORE HAOS dashboard audit

**Scope:** first controlled inspection of CORE. No HOME rollout, no writes.

## Supervisor and permissions

- `map: [{type: homeassistant_config, read_only: true}]` mounts Home Assistant configuration at `/homeassistant`; the runtime verifies mount is read-only.
- The App keeps `homeassistant_api: false` (not requested), no Supervisor HA control, no writable HA filesystem mount, no Apply option. The only mutable path remains the App's pre-existing private `/data` MQTT inventory.
- Ingress admin-only, GET-only. Every POST responds with HTTP 405. The default page does not fetch GitHub or enumerate HA files; separate links explicitly trigger those operations.

## Source and local comparison

- From v0.2.1, a read-only GitHub preview accepts any repository owned by DigitalHouses, resolves its default branch to a SHA for the requested inspection, and enumerates its dashboards/ru/*.yaml without hardcoded product pins or version gates.
- No MQTT-provided URL/ref is used to choose a Git download, and no dashboard filenames are advertised via MQTT.
- The local audit scans only `dashboards/dh/ui.yaml` and bounded `dashboards/dh/views/*.yaml|*.yml` from CORE. It matches views by their Lovelace `path` (not only by basename), and checks a filename collision separately.
- For each canonical view, compare raw bytes (SHA-256), parsed YAML semantic equality, or produce a bounded escaped unified diff (45 lines / 4500 characters maximum). Differences are shown only for allowlisted dashboard-view YAML, never `secrets.yaml` or other HA settings.
- Scan Lovelace Storage view paths from `.storage/lovelace` and `.storage/lovelace.*`, including modern `.storage/lovelace.<dashboard>` names. Reject malformed Storage; return only collision results, **never** Storage JSON or unrelated keys/attributes.
- Symlinks, missing/unverified read-only mount, unreadable data, oversized files and parse failures return a visible non-mutating error. A Storage path match blocks silent YAML adoption.

## What is expected from the first live CORE screenshot

| Canonical source | Expected path | Possible observation |
| --- | --- | --- |
| PVE Proxmox `10_pve_proxmox.yaml` | `dh_pve_agent` | identical / semantically equal / changed / missing / conflict |
| PVE UPS `11_pve_ups.yaml` | `dh_pve_agent_ups` | identical / semantically equal / changed / missing / conflict |
| Plex `10_plex.yaml` | `dh-plex-agent` | a local YAML match, absent, or a Lovelace Storage conflict |

The current view remains **read-only** regardless of status. `GitHub owner DigitalHouses` is a source admission result, not proof of compatibility or permission to Apply.

## Separate future transaction stage (not enabled)

1. Audit real CORE files and identify any Storage-owned dashboards and managed/legacy ownership. Resolve duplicate paths without deleting existing user resources.
2. Design an explicit per-product transaction: PVE Proxmox+UPS as a single unit; Plex dashboard and Recorder package require distinct handling and must never create parallel Recorder configs.
3. Capture exact original file bytes, mode, owner, SHA-256 and transaction journal into private App storage before a write. Ensure consistency and backups before any replacement.
4. Require user approval of a fingerprint based on current files, immutable Git SHA, agent version and target path. Re-evaluate all inputs immediately before changing files; refuse if changed.
5. Apply only explicitly owned and validated files, validate HA configuration, roll back all files in the product batch on failure, and expose manual rollback. Do not write `.storage` directly or restart HA automatically.
6. Only after successful CORE application and rollback acceptance consider HOME rollout. Until then, historical experimental `sync_engine.py` remains disabled in the shipped runtime.

## Relevant automated tests

`tests/test_local_audit.py` covers two PVE views, missing Plex, different and equivalent YAML, renamed local filename, colliding basename and path, Lovelace Storage format and privacy, malformed Storage, symlink denial, missing mount, GET-on-demand and POST 405.
