# DigitalHouses PBS Agent

## 0.1.11

- Show the existing MQTT `switch.dh_pbs_agent_auto_update` as **Автообновление**
  in the **Диагностика → PBS Agent** entities card.
- Reuse PVE Agent's native `custom:auto-entities` +
  `custom:entity-progress-card-template` storage cards for each actual PBS
  datastore (used/total GiB, used percent, health colour, more-info).
- Remove duplicated datastore usage from the backup tree; retain group inventory
  and backup freshness there. Identify datastore sensors by portable MQTT role
  attributes, not by site-specific names.
- Add per-datastore capacity and health metadata to existing MQTT usage sensors,
  retaining their unique IDs, topics and display names. For S3 / unavailable
  capacity, show an explicit unknown state, not fabricated space.
- Preserve OFF-by-default auto-update, all existing MQTT topic/ID contracts,
  operational logic, scheduled jobs, and monitoring semantics.


## 0.1.10

- Use one release-aware installer command to resolve the newest *published stable*
  PBS Agent tag, while continuing to support explicitly pinned immutable tags
  and existing unattended --set / safe-secret options.
- Suppress Git detached-HEAD advice for expected tag checkouts.
- Add PVE-style MQTT Refresh, Check Updates, Install Update and Restart Agent
  buttons, plus opt-in auto-update switch and authoritative state sensors.
- Add unified status/control header and preserve native PBS health/dynamic
  datastore/job trees. Installed HA entity identities remain stable.
- Run self-update/restart through a separate systemd oneshot worker with
  durable operation outcomes; no PBS service restart, job changes or new
  management daemon.
- Retain native CLI config/set/status/restart/update and add check-update and
  auto-update on/off/status commands. Maintain /root/dh-pbs-agent.txt.


## 0.1.9

- Display local datastore USED / TOTAL GiB and percent USED in the compact
  PBS tree, using actual native PBS used_bytes and total_bytes.
- Localize Home Assistant MQTT Discovery display names for existing health,
  network, ZFS, backup, sync, datastore, job, and event entities into Russian.
- Preserve every MQTT unique_id, entity ID, event_type, state, command topic,
  role marker and PBS job identity; S3 capacity is not invented.
- Keep standalone native HA Dashboard (no mandatory custom cards).


## 0.1.8

- Restore a fully standalone PBS View using native Home Assistant entities
  and Markdown cards. Remove the mandatory custom:auto-entities dependency
  added in 0.1.7 that can leave a HOME dashboard blank.
- Keep dynamically named datastore and job entries using the PBS state
  arrays, and show both MQTT Number settings in a native entities card.
- Preserve 0.1.7 MQTT per-store/per-job Discovery metadata for optional
  Auto Entities cards elsewhere. No changes to MQTT IDs, PBS jobs or alerts.


## 0.1.7

- Tag MQTT sensors with stable pbs_product, pbs_section, pbs_metric,
  pbs_display_name and pbs_instance attributes for portable Auto Entities.
- Discover per-job diagnostic sensors using the actual PBS task type/ID and
  remove obsolete job components when the PBS inventory changes.
- Resolve the View's health source by product/section metadata instead of a
  fixed installed entity ID. Render status, diagnostics, and Number controls
  via Auto Entities filters.
- Preserve current MQTT unique IDs and monitoring/alert semantics. No site
  name or datastore/job ID is hardcoded in the View.


## 0.1.6

- Show each PBS maintenance job schedule on its own nested clock line,
  then its status, name, and last execution beneath it.
- Preserve actual PBS schedule strings and local display of last-run times.
- Render consistent tree branches for multiple job types and multiple jobs;
  no changes to PBS collection, MQTT entities, alerts, DH Sync or CORE.


## 0.1.5

- Replace both INI dashboard display limits with two native Home Assistant MQTT
  Number entities in the existing PBS Agent device (backup groups and recent
  task events), default 10 each. Changes take effect immediately.
- Keep limits in the agent's existing atomic state directory, surviving
  service/broker restarts, without additional background services.
- Keep current tree view, entity identity, PBS collection, monitoring and
  DH Sync placement unchanged. Retained MQTT state carries view_limits.


## 0.1.4

- Display datastore free/total GiB and percentage free on a nested tree line,
  with no fabricated remote S3 capacity.
- Hide redundant status text for unmonitored backup groups.
- Add two independent native INI dashboard limits (default 10 each):
  backup_groups_limit and task_events_limit, published through existing MQTT
  health attributes for DH Sync. Display settings do not change monitoring.
- Preserve PBS job history and existing alert/Sync contracts.


## 0.1.3

- Replace the three wide Markdown PBS tables with compact status trees,
  following the existing PVE Agent monospaced `├─` / `└─` style.
  Group datastore usage, backup inventory, freshness checks, maintenance
  jobs and latest task history without losing diagnostic information.
- Identify native PBS S3-backed datastores from the existing datastore
  configuration. Show their status as S3 without treating the local S3 cache
  percentage as the Backblaze bucket's remote capacity.
- Include native PBS Pull Sync jobs in the maintenance tree, including S3
  target jobs and their actual last-run result. Preserve the existing Push
  Sync sensor and alerts. No external rclone/Backblaze App job monitoring.
- Keep the same View path and MQTT entity IDs; no PVE/DH Sync/CORE changes.

## 0.1.2

- Extend the existing DH System PBS View with actual scheduled Sync/Verify/Prune/GC
  job rows, last-run statuses, recent native PBS task results, and visible
  VM/CT/Host backup groups across namespaces.
- Keep the existing PBS status, datastore capacity, freshness-rule and
  diagnostics cards; distinguish unmonitored backups from verified healthy
  backups instead of displaying a fabricated OK.
- Use only local read-only PBS API GET and the existing manager task list;
  namespace/group inventory is optional and reports partial availability
  without interrupting the existing PBS monitoring.
- Present human-readable Markdown tables without external frontend cards;
  preserve the same MQTT Discovery entities and DH Sync view path.

## 0.1.1

- Add official DigitalHouses Stats HTTPS telemetry (protocol v1 / policy v2).
- Persist UUIDv4 installation ID and private 256-bit token in the existing agent state directory; send only product ID, release version and installation UUID about once per day.
- Use release tag plus exact BUILD_INFO commit gate; retry failures after at least one hour without affecting PBS monitoring.
- Support authenticated erasure and local identity rotation through the native dh-pbs-agent telemetry-delete command.
- Add [telemetry] enabled to existing INI/CLI. Fresh-install default true per shared agent policy; legacy installations must explicitly set true before upgrading to avoid silent activation or monitoring interruption.


## 0.1.0

- First Linux/systemd PBS monitor: read-only status of PBS datastores, snapshots, backup freshness, sync/verify/prune/GC jobs and ZFS.
- MQTT Discovery with instance identity, retained current state, transient machine events and DH Sync 0.6.0 retained product announcement.
- HOME-first canonical Lovelace view and portable Russian notification package.
- Native INI, CLI and release-tag installer; no Plex/PVE/Ansible changes.

Production acceptance is conditional on live HOME PBS v4.x validation and repository CI.
