# DigitalHouses PBS Agent

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
