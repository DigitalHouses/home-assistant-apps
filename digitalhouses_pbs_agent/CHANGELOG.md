# DigitalHouses PBS Agent

## 0.1.20

- Replace the static inline-SVG datastore chart with Home Assistant's
  native **statistics-graph** bar card, exactly following the established
  DigitalHouses Backblaze history pattern. The 30-day daily columns have
  built-in hover tooltips showing the date and actual numeric GiB value.
- Discover one real numeric MQTT sensor per configured datastore
  (`sensor.dh_pbs_agent_datastore_<name>_used_gib`) from live PBS
  `used_bytes`, with `unit_of_measurement: GiB`,
  `state_class: measurement` and stable existing datastore provenance
  metadata. HA Recorder owns the long-term statistics; no custom graphing
  library, new HACS dependency or separate database is needed.
- Use existing installed `custom:auto-entities` to pass dynamic datastore
  sensors into the native `statistics-graph`, with `chart_type: bar`,
  `period: day`, `days_to_show: 30`, `stat_types: [max]`.
  Explicitly label the chart as the **daily maximum** occupied capacity,
  not the last reading of a day or sum of uploaded VM/CT snapshot sizes.
- The new numeric sensor's Recorder history begins after installation;
  old PBS RRD readings are **not** automatically backfilled into HA.
  Omit unavailable/S3 capacity rather than representing it as zero.
- Delete the now-unneeded custom SVG renderer, retained HTML chart MQTT
  sensor/topic publications and additional PBS RRD API polling path.
  Retain the existing four-section dashboard layout with the graph at
  the bottom of column 2, PVE-parity management card, backup trees and
  all PBS/CORE backup jobs unchanged.


## 0.1.19

- Align the **actual PBS Agent CLI** with current PVE Agent 0.5.96,
  per the mandatory DigitalHouses Linux Agent Management Standard.
  The old flat `status` becomes a compact, aligned, sectioned
  `DigitalHouses PBS Agent <version> | commit <commit>` overview:
  `SYSTEM`, `MQTT`, `PBS`, `MONITORING`, `UPDATES`, `TELEMETRY`.
  All product facts come from the existing local runtime cache; no
  status-time PBS/MQTT network probes, fabricated current health, or
  new background service.
- Match PVE CLI messages exactly for common operations:
  `UP_TO_DATE version`, `UPDATING old -> target` **before** installation,
  `UPDATED version` only after verifying the installed version,
  `Restarted digitalhouses_pbs_agent.service`, `CHANGED`/
  `UNCHANGED`, `CHANGED ON/OFF`, `UNCHANGED ON/OFF`, and
  `ERROR: ...` without Python exception names or secret values.
- Use PVE-style absolute-path `help`, native INI keys and limits,
  safe hidden-password instructions, configuration transaction rollback
  on failed service restart, and refusal to start stopped Agents
  through `restart` or `update`. Keep PBS-specific commands.
- Base the **canonical HA control card** directly on the maintained PVE
  Dashboard (exact Russian status-operation text, timer, colors,
  four chip labels/order and confirmation placement). Use PBS entity
  IDs, functional icon and safe PBS-only confirmations. Preserve
  the already required from/target version pair while installing.
- Keep all four PBS Dashboard sections, datastore chart and trees,
  original MQTT identities, existing PBS/local job semantics, and
  read-only collection. PVE/Plex implementations are untouched.
- Add golden-output CLI and HA parity tests against the **current**
  PVE source, plus installer validation, failure and rollback cases.


## 0.1.18

- Restore the original four-section PBS Dashboard layout: move the new
  30-day occupied-disk chart to the bottom of the second section, after
  datastore cards and backup-group tree. Remove two-column spanning and
  chart horizontal scrollbar.
- Fix RRD cache not initialized on PBS 4.2: a direct in-process
  debug CLI call does not own the server RRD cache. Query the monthly
  RRD through the standard PBS localhost HTTPS proxy CLI mode instead,
  which accesses the running service's initialized cache.
  Only the optional RRD history call changes transport.
- Align operational feedback with PVE Agent: installed vX -> target vY
  before and during installation, persistent from/target attributes,
  exact version-check result, tenths-of-a-second timer/duration,
  error details and time since last successful collection.
- Verify the actual running version reaches the target before marking
  a completed updater worker as successful. Keep MQTT topic identity,
  background checks, native worker, five-second result lifecycle
  and auto-update semantics. No backup-job or DH Sync changes.


## 0.1.17

- Add a 30-day daily bar graph for **physically used datastore filesystem
  capacity**. Use the native read-only PBS
  `admin/datastore/{store}/rrd?timeframe=month&cf=AVERAGE` data source and
  each day's last valid RRD point; today's current datastore status is used
  as the most recent measurement.
- Agent prepares the 30 HA-timezone day buckets, real GiB values, tooltip
  times, scaled bars, ranges and deltas. Dynamic local datastores are supported.
  Missing days stay empty; no interpolation, fake zeroes or database.
- Render a compact accessible inline SVG in one retained MQTT diagnostic
  sensor. The existing button-card displays its ready-made HTML without
  doing chart arithmetic or requiring another frontend dependency.
- Standalone RRD read errors do not downgrade PBS health; show today's
  live value and the reason when historical RRD is unavailable.
- Preserve existing jobs, backups, backup-group and task history trees,
  telemetry, DH Sync contracts, and view-limit controls.


## 0.1.16

- Fix observed HOME PBS 4.2.10 incremental-size diagnostics:
  0/32 with nine API errors and 23 deleted-history snapshots.
- Read the exact new compressed chunk bytes from the immutable PBS snapshot
  manifest (index.json.blob, unprotected.chunk_upload_stats.compressed_size),
  decoded read-only with native proxmox-backup-debug inspect file.
- Use the datastore path supplied by the PBS configuration; verify the
  namespace, guest identity and snapshot timestamp before attributing a size.
  Preserve the existing snapshot-information API as a fallback for backends
  without a local manifest, including S3.
- Do not use full logical backup sizes or assign a fabricated value to old
  tasks whose snapshots were deleted. Keep previous compact trees.
- Expose the first bounded PBS size-source error as diagnostic sensor
  attribute sample_error, alongside existing reason counters. No credentials,
  HA UI computation, new daemon or PBS scheduler changes.


## 0.1.15

- **Agent owns all tree calculations**: four ready-to-display retained MQTT
  texts (backup groups, maintenance jobs, task history, summary). Lovelace
  only displays their content. Datastore card names, capacity text, percentages,
  icons and colours are also prepared by the Agent, not HA templates.
- **Automatic freshness**: every discovered PBS group is monitored against a
  default 36-hour threshold; optional existing per-group backup_rules override
  it. Green means a recent snapshot; red means it is stale. Existing event
  state/recovery is preserved and extended to the auto-monitored groups.
- **Home Assistant timezone as source**: one canonical DH Sync common package
  publishes HA's IANA timezone to retained MQTT. The Agent caches and applies
  that timezone to all tree dates and times, including midnight crossings.
  If it has not arrived, the tree explicitly warns that UTC is temporary.
- Group inventory additionally shows the compressed increment of the last
  snapshot only when it matches a completed task exactly; never substitute
  logical size for missing stats.
- **Diagnose missing uploaded-size values**: report counts of missing snapshot,
  ambiguous match, PBS API failure and absent upload statistics through a
  diagnostic sensor, without faking a full snapshot size or 0 bytes. The
  incremental metric remains the PBS compressed chunk upload size.
- Preserve existing MQTT IDs, native PBS read-only monitoring, dynamic
  datastore/job discovery, Number limits and no PBS scheduler changes.


## 0.1.14

- Show the real compressed upload of a completed PBS Backup as
  `+0.11 GiB` (or MiB for small payloads) in the task-history tree.
- Read `snapshot-information.upload-statistics.compressed-size` for a
  verifiably matching guest, datastore, namespace and snapshot time.
  Never report logical snapshot size as daily incremental upload.
- Missing, deleted, ambiguous or in-progress snapshots show no transfer
  value. Preserve existing PBS health, alert scope and task status.
- Cache immutable upload statistics per running process; use native
  read-only PBS API with no new daemon, credentials or configuration.


## 0.1.13

- Show the actual VM/CT guest ID beside native PBS Backup tasks when the
  worker identity is explicitly present in PBS worker_id or UPID
  (e.g. `Backup VM1234`, `Backup CT1221`); otherwise keep `Backup`.
- Add the daily event count to each HA-local date in the task-history tree
  (`📅 DD.MM.YYYY (5)`). The count reflects the day's tasks available from
  PBS, even if only part of the day's history is shown under the configured
  MQTT Number display limit.
- Preserve chronological order, native task status/duration and HA-local
  date/time conversion. No new PBS API requests, services or configuration.


## 0.1.12

- Group the **Последние выполнения PBS** tree by actual run date, with a
  calendar icon per day and indented time/status/duration rows.
- Format both dates and times in the configured Home Assistant timezone
  using `as_local(as_datetime(...))`, including midnight crossings.
- Preserve newest-first event order, native PBS status, independent event
  limit, overflow notice and empty-history state. View-only change.


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
