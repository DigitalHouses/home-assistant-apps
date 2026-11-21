# DigitalHouses PBS Agent v0.1.14

Standalone **read-only** Linux/systemd monitoring agent for a local Proxmox Backup
Server 4.x. HOME pilot: Debian MediaServer/PBS VM; no dependency on Plex Agent,
PVE Agent, Cloudflare, Tailscale, Ansible or CORE.

## Source of truth

- Native INI: /etc/digitalhouses_pbs_agent/digitalhouses_pbs_agent.conf
- State: /var/lib/digitalhouses_pbs_agent (small atomic JSON, no database)
- Service: digitalhouses_pbs_agent.service
- CLI: /usr/local/bin/dh-pbs-agent
- Cheat sheet: /root/dh-pbs-agent.txt
- Canonical DH Sync 0.6.0 view: dashboards/ru/13_pbs.yaml, path dh_pbs_agent
- Canonical RU notifications: packages/locales/ru/dh_pbs_agent_notification_local_package.yaml

Like PVE Agent, the PBS Agent runs locally as root and reads the installed
PBS API with `proxmox-backup-debug api get` and `PROXMOX_DEBUG_API_CODE=1`.
No PBS API token, external HTTPS connection, certificate settings, or extra
monitoring service are needed. The systemd service retains `ProtectSystem=full`,
with a narrow writable exception for `/etc/proxmox-backup` because PBS itself
opens `.datastore.lck` even for read-only datastore status and GC queries.
It observes PBS server version, datastore
status, snapshots, **push** sync, verify, prune and GC jobs, plus local
read-only ZFS and filesystem status. It does not run or
edit PBS jobs, backup snapshots, PVE jobs, Plex, ZFS or retention.
A job appearing as OK is **not** proof of restore verification.

## Actual uploaded increment per PBS snapshot (v0.1.14)

**Последние выполнения PBS** shows the amount of compressed *new chunk
payload uploaded in that run* next to the VM/CT, such as
`Backup VM2222 · +0.11 GiB · 32 с · OK`. It is taken from the native
PBS `admin/datastore/<store>/snapshot-information` endpoint,
`upload-statistics.compressed-size`, and is **not** the total logical
snapshot size nor the exact net disk-space increase after deduplication.

The Agent matches an actual completed backup task with its guest,
datastore, namespace and snapshot time. Ambiguous, missing, deleted,
in-progress or unreported snapshots have **no amount shown**; the Agent
never substitutes the logical size or zero. This optional metric does
not change PBS health or generate alerts. Data is fetched read-only and
immutable results are cached for the running Agent process to avoid
repeating detail queries on every 5-minute poll.

## Backup guest identity and day totals (v0.1.13)

The task-history tree labels each date with a count of **all tasks available
in the PBS history for that date**, even when the user-configured display limit
shows fewer task lines. Counts are bounded by the tasks returned by PBS and
are not a guarantee of exhaustive historical coverage.

For native PBS `backup` tasks, the Agent extracts a guest identity
(`VM1234` or `CT1221`) only when the actual PBS `worker_id`, `worker-id`
or its encoded UPID explicitly includes a datastore and `vm-1234` /
`ct-1221`. If PBS does not supply a recognizable guest identity, the task
remains named `Backup`; no inference from group inventory or timestamps.
The original task identifier, duration and result remain unchanged.
Dates and times continue to use Home Assistant's configured timezone.

## PBS task history by Home Assistant local date (v0.1.12)

In **Последние выполнения PBS**, actual native PBS task history is grouped
under `📅 DD.MM.YYYY` rows. Each task shows `HH:MM · Type · Duration · Status`
with its status icon. **Both date and time** are computed by Home Assistant's
`as_local(as_datetime(e.started_at))`, not the PBS server timezone. The
newest-first ordering and user-configurable MQTT Number event limit are kept;
if the history exceeds the limit, the remainder count stays visible.
No MQTT identity, collector behavior or PBS task logic changes.

## Dynamic PBS storage progress cards (v0.1.11)

The **Хранилища PBS** section now matches PVE Agent's storage UI: one
`custom:entity-progress-card-template` per datastore, generated using
`custom:auto-entities`. Each local datastore displays its real name, used
percentage, used/total GiB, health-based colour and a more-info action.
MQTT Discovery exposes `total_gib`, `used_gib`, `pbs_health` and
`pbs_backend` on the existing `used_percent` sensor. No datastore
name or entity ID is hardcoded in the View.

An S3 backend or missing capacity displays an explicit unavailable-capacity
message instead of inventing remote usage. The former datastore branch has
been removed from the backup inventory tree to avoid duplicate information;
the tree still shows backup groups and freshness checks.

This section uses the **same installed frontend components as PVE Agent**:
`custom:auto-entities` and `custom:entity-progress-card-template`.
The rest of the PBS View continues to use native HA cards and the already
adopted PVE Agent status header.

The existing MQTT auto-update switch is shown in
**Диагностика → PBS Agent**.

## One-command installation and PVE-style management (v0.1.10)

Run on the PBS Linux VM as root; this fetches the installer from the
DigitalHouses repository and **pins its actual install to the latest published
stable immutable PBS Agent release** (never a branch head):

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/DigitalHouses/home-assistant-apps/main/digitalhouses_pbs_agent/install.sh)
```

On an existing host the native INI is preserved, so no options or extra
configuration are needed. For a fresh, fully unattended installation supply
the real MQTT broker and the local PBS datastore names (change for the site):

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/DigitalHouses/home-assistant-apps/main/digitalhouses_pbs_agent/install.sh) --non-interactive --set mqtt_host=192.168.11.222 --set pbs_datastores=pbs-serzhan
```

To pin a known release, set `DIGITALHOUSES_SOURCE_REF=digitalhouses_pbs_agent-vX.Y.Z`.
Passwords are passed only with `--mqtt-password-stdin` or hidden
`dh-pbs-agent set mqtt_password`, never with literal command arguments.
The installer validates the version, performs rollback on installation
failure and suppresses Git's harmless detached-HEAD advice.

Daily management (absolute paths in `/root/dh-pbs-agent.txt`):

```bash
dh-pbs-agent status
dh-pbs-agent restart
dh-pbs-agent check-update
dh-pbs-agent update
dh-pbs-agent auto-update on
dh-pbs-agent auto-update off
dh-pbs-agent auto-update status
dh-pbs-agent set mqtt_host=192.168.11.222 mqtt_port=1883
dh-pbs-agent help
```

The CLI works without MQTT; `set` retains native INI semantics and existing
credentials. The MQTT device contains native buttons
`button.dh_pbs_agent_refresh`,
`button.dh_pbs_agent_check_updates`,
`button.dh_pbs_agent_update` and
`button.dh_pbs_agent_restart_agent`, plus the persistent
`switch.dh_pbs_agent_auto_update` (OFF by default).
The status card uses `sensor.dh_pbs_agent_card` and exact user-operation
states; update-check and manual refresh have their own diagnostic sensors.
The independent `digitalhouses_pbs_agent-control.service` oneshot worker
handles install/restart so that the monitoring agent does not replace itself
inside its own MQTT callback. Its state is retained in the existing state
directory and checked after an agent restart. Manual Refresh is real,
on-demand PBS collection, not a service restart or republish of cached data.
The source of update availability is a verified **published stable GitHub
Release**. Repeated presses do not queue duplicate work.

The canonical View header follows PVE Agent's
`custom:button-card` + `custom:mushroom-chips-card` layout.
Those two frontend resources must be installed for the unified header;
PBS backup/job trees and main native entities cards do not require Auto Entities;
the storage progress section does, just as the PVE storage section does.
The UI asks for confirmation before installation and restart.

The shared reference requirements are:
- [Linux Agent Management Standard](../docs/standards/DH_LINUX_AGENT_MANAGEMENT_STANDARD.md)
- [Unified Product Status Card Standard](../docs/standards/UNIFIED_PRODUCT_STATUS_CARD_STANDARD.md)
- [Manual Refresh Standard](../docs/standards/MANUAL_REFRESH_STANDARD.md)

## Used capacity and Russian entity names (v0.1.9)

The local datastore tree now shows USED / TOTAL GiB (percent USED), directly
from native PBS used_bytes/total_bytes; previously it displayed FREE / TOTAL.
For S3-backed datastores it keeps the backend/status rather than claiming
remote bucket capacity.

Human-facing MQTT Discovery names (including per-datastore and per-job
sensors, event entities and main diagnostic sensors) are localized into
Russian. The actual PBS datastore/job names remain unchanged and are always
dynamic. Technical MQTT unique IDs, topics, Home Assistant entity IDs and
status/event values are unchanged to preserve existing dashboards and alerts.
Home Assistant may preserve a custom name assigned previously by a user.

## Standalone Home Assistant View (v0.1.8)

The canonical Dashboard now requires only native Home Assistant cards.
The mandatory Auto Entities cards introduced by v0.1.7 were removed because
they can leave the View unavailable if that frontend component is missing.
The main health and diagnostic entity IDs are intentionally stable across
separate HA installations and do not contain any installed datastore or job
names. The datastore and job trees continue to render those names dynamically
from PBS telemetry.

Two existing MQTT Number controls are shown in a standard entities card:
number.dh_pbs_agent_backup_groups_limit and
number.dh_pbs_agent_task_events_limit. The portable MQTT role metadata
introduced in v0.1.7 remains available to use with Auto Entities in optional
cards later; it is not mandatory for displaying PBS status.

## Portable MQTT Discovery and dynamic Views (v0.1.7)

All datastore, backup-group, and scheduled-job names are taken from local PBS
rather than from a HOME-specific list. The existing per-datastore MQTT sensors
are labelled with portable entity attributes:
- pbs_product = digitalhouses_pbs_agent
- pbs_section = datastore
- pbs_metric = used_percent or available_gib
- pbs_display_name = the actual datastore name
- pbs_instance = instance_id

Actual PBS maintenance jobs are now individual MQTT diagnostic sensors in
the same device, with pbs_section=job, pbs_metric=status, pbs_job_type,
pbs_job_id, pbs_display_name, schedule, and last_run_at. Their entity
identities are stable for unchanged PBS type and ID; renamed or removed jobs
are removed from MQTT Discovery. Discovery inventory is retained locally in
the existing state directory, without extra services.

Existing core and datastore unique_id values are retained; new installations
in separate Home Assistant instances use the same stable base entity IDs.
The canonical View reads that stable health sensor, while all displayed PBS
store and job names come from the native state data.
Optional custom:auto-entities cards can use these metadata filters when
the frontend resource is installed; the canonical PBS View does not require it.

Example portable datastore filter, for an optional future card:

~~~yaml
type: custom:auto-entities
card:
  type: entities
  title: Datastores
filter:
  include:
    - attributes:
        pbs_product: digitalhouses_pbs_agent
        pbs_section: datastore
        pbs_metric: used_percent
~~~

For an optional job list, change pbs_section to job and pbs_metric to status.
There are no hardcoded PBS datastore names or job IDs in the View.

## Maintenance schedule tree (v0.1.6)

The PBS jobs card shows a compact hierarchy: job type > clock and native PBS
schedule > actual last-run result. A timestamp on the result line is converted
to the Home Assistant local timezone; the schedule string is displayed exactly
as PBS reports it and is not a timestamp. Multiple jobs of a type have separate
schedule and result pairs. No task configuration is modified.

## MQTT Number controls for tree display (v0.1.5)

Both display limits are MQTT Number entities belonging to the existing PBS
Agent device in Home Assistant (Settings > Devices & services > MQTT):
- 'Групп резервных копий' (1..80, default 10)
- 'Последних событий' (1..50, default 10)

Changing either number updates the retained PBS health state and View
immediately. Values survive service restarts in the existing
/var/lib/digitalhouses_pbs_agent/view_limits.json atomic state file, not
in the native INI. No manual MQTT publish or service restart is needed.

The previous v0.1.4 [dashboard] INI keys are no longer used. Existing INI
files are otherwise preserved by the installer. No PBS tasks, alerts, backup
freshness thresholds or Sync operations are changed.

Datastores continue to show the name on one line and free/total GiB with the
actual free percentage on the second line. S3 datastores retain backend status
rather than showing a misleading cloud-capacity percentage.

## Compact PBS dashboard and native S3 monitoring (v0.1.3)

The canonical PBS View now uses the same compact text tree convention as
PVE Agent, with `├─`/`└─` branches and state icons. Datastores, backup
snapshot groups, freshness rules, Sync/Verify/Prune/GC jobs and up to six
recent tasks are shown without wide tables. The View uses existing HA
entities; DH Sync will fetch it from the main branch.

PBS 4.2 native S3-backed datastores can be distinguished via their `backend`
configuration, but must be included in the native `pbs_datastores` list.
Local-target Pull Sync jobs are now included in the maintenance tree; when
the destination datastore uses the PBS S3 backend the job is marked `S3 Sync`
with its actual last-run state. These results come from PBS, not directly
from the S3 provider. S3 datastore capacity may reflect the local cache,
so the tree intentionally does not report it as cloud bucket free space.
**External rclone/restic/Backblaze App jobs are not monitored by PBS Agent.**

## PBS dashboard data in v0.1.2

The existing `dh_pbs_agent` View now renders four factual tables: datastore
usage, backup groups (`admin/datastore/{store}/groups` with discovered
namespaces), Sync/Verify/Prune/GC jobs (schedule, last run and result), and
recent tasks (up to 12) from the same existing native
`proxmox-backup-manager task list --all true` call. No external APIs, no
new service and no PVE changes. Backup groups with no configured freshness
rule are displayed **without a monitored OK status**. Empty/partial task or
group data are visibly labeled rather than silently shown as healthy.

For large datastores the displayed group inventory is capped at the 80 most
recent groups; when truncated, the View displays a partial-coverage warning.
New MQTT attributes require the v0.1.2 agent to be installed; the YAML View
itself is fetched from GitHub `main` by DH Sync on refresh.

## HOME installation / release

Install only from the published immutable GitHub Release:

For a published release, on the local PBS VM as root:

~~~bash
DIGITALHOUSES_SOURCE_REF=digitalhouses_pbs_agent-v0.1.9 \
  bash install.sh --non-interactive \
  --set mqtt_host=YOUR_MQTT_HOST \
  --set pbs_datastores=YOUR_PBS_DATASTORE
~~~

For existing v0.1.0 installations, add `--set telemetry_enabled=true` to this
installer command after accepting the telemetry/privacy policy. The installer
checks this BEFORE stopping the existing service. Without that setting, it
refuses the upgrade and leaves v0.1.0 running. This prevents a silent telemetry
opt-in or a monitoring interruption.

No PBS token is created, requested, or stored. The only optional credential
is the MQTT password, handled by the existing native CLI/installer stdin
mechanism. HOME and CORE addresses are not hard-coded into the product.

An existing installation retains its INI. The installer stages a GitHub release
tag and compares VERSION with the tag. A failed update rolls back the prior
agent source and native config; it never restarts PBS or Plex services.

## Native config and CLI

```ini
[general]
instance_id = pbs_home
log_level = info

[mqtt]
host = mqtt-server
port = 1883
username =
password =
keepalive_seconds = 60

[pbs]
datastores = pbs-home

[telemetry]
enabled = true

[monitor]
poll_seconds = 300
backup_rules = pbs-home|-|vm/2222|36
sync_rules = push-home|36
warning_percent = 80
critical_percent = 90

```

The two freshness rule lists are optional. Each `backup_rules` rule is
`datastore|namespace-or--|vm/VMID-or-ct/ID-or-host/NAME|max_age_hours`,
separated by `;`. An explicitly configured missing snapshot is reported
`NO_SNAPSHOT`, not healthy. Old/unmonitored historical groups do not create
alerts. `sync_rules` has `job_id|max_age_hours` entries, also separated by
`;`. Only local HOME Push Sync is monitored; this version does not inspect
remote CORE PBS. If no Push Job is configured, state is `NOT_CONFIGURED`,
never success. Freshness SLA is never guessed.

```bash
/usr/local/bin/dh-pbs-agent status
/usr/local/bin/dh-pbs-agent set monitor_backup_rules='pbs-home|-|vm/2222|36'
/usr/local/bin/dh-pbs-agent set monitor_sync_rules='push-home|36'
/usr/local/bin/dh-pbs-agent set monitor_warning_percent=80 monitor_critical_percent=90
/usr/local/bin/dh-pbs-agent set mqtt_password      # hidden prompt
printf '%s\n' "$MQTT_PASSWORD" | /usr/local/bin/dh-pbs-agent set mqtt_password=-
/usr/local/bin/dh-pbs-agent telemetry-delete
/usr/local/bin/dh-pbs-agent restart
/usr/local/bin/dh-pbs-agent update
/usr/local/bin/dh-pbs-agent help
```

`set` validates the effective entire INI before atomic replace,
preserves unrelated INI lines and restarts **only its own active service**
once for a real change. Unchanged values print `UNCHANGED`.
No silent auto-update daemon or second update mechanism is installed.
`update` checks GitHub Releases and installs a newer stable immutable tag.
Use `--non-interactive --set ...` for automation; secrets do not belong
in command arguments.

## MQTT / Home Assistant / DH Sync

One MQTT client per agent instance; root:
`DigitalHouses/Global/digitalhouses_pbs_agent/<instance>`.

- `/sync`: QoS1 retained declaration only `schema,product_id,type,version,repository,product_path`. Published on every MQTT connect/reconnect. Never depends on availability for DH Sync.
- `/state`: QoS1 retained current observations. No per-group HA entity explosion.
- `/availability`: QoS1 retained online/offline LWT.
- `/event/backup`, `/event/sync`, `/event/storage`, `/event/maintenance`: QoS1 transient, **retain=false**.
- HA entity prefixes: `sensor.dh_pbs_agent_*`,
  `binary_sensor.dh_pbs_agent_problem`, `event.dh_pbs_agent_*_event`.
- Actual Linux hostname/IP from host route to MQTT; ambiguous IP = unknown.
- Russian notifications are **only** in the standard HA package
  (`event.received -> trigger.id -> choose -> persistent_notification.create`),
  not in machine event payloads.
- DH Sync alone decides dashboard placement, ordering, title, icon and access.
  Give its profile chat **product_id = digitalhouses_pbs_agent** and
  **path = dh_pbs_agent**. No cross-product dashboard file edits.

## Health and facts

`HEALTHY`: all configured observability checks returned credible healthy
values. `DEGRADED`: warning capacity or failed recent job.
`CRITICAL`: overdue explicitly required snapshots/Push, critical storage or
degraded ZFS. `UNKNOWN` / `UNAVAILABLE`: required evidence cannot
be read; never substitute 0 or success. If a backup or sync rule is not
configured, no freshness guarantee is asserted.

CLI/API collection failure is explicit. All PBS reads are executed locally
under the root-owned systemd service, analogously to PVE Agent's `pvesh get`.
For read-only datastore and job configuration APIs the agent invokes
`proxmox-backup-debug api get` with `PROXMOX_DEBUG_API_CODE=1`.
For running/completed task history it uses the supported native
`proxmox-backup-manager task list --all true` command: the direct debug API
cannot initialize PBS WorkerTask in a standalone process. Neither interface
requires a stored PBS token or loopback HTTPS. No create/set/delete operations
are performed. ZFS commands are read-only `zpool list`, no scrub/import/destroy.
Snapshots use PBS metadata, not archive contents or chunk scans.

## Historical v0.1.0 pilot acceptance checklist

1. On HOME PBS 4.x verify local root CLI and actual JSON shapes of
   `/admin/sync`, `/admin/verify`, `/admin/prune`, `/admin/datastore/<store>/gc`,
   and `/admin/datastore/<store>/snapshots`.
2. Verify actual Push Job, Verify/Prune/GC status and ZFS datastore metrics.
3. Confirm missing and overdue snapshot transitions, retained state,
   deduplicated MQTT machine events, reconnection and notifications.
4. Verify root CLI online/offline, atomic `set` and update rollback, no
   effect on Plex/PVE/PBS services.
5. Run `python3 -m unittest discover -s tests -v` in the product and
   repository validator `python scripts/validate_repository.py`.

Scope remains HOME only for the pilot. Ansible and CORE are managed separately.

## Product telemetry (0.1.1)

The single native INI switch is `[telemetry] enabled = true|false`. Fresh
installations default to true (Linux Agent policy). The operator must review
the privacy terms and legal conditions; a default-on value is not itself
proof of consent. Existing installations retain their INI and **must explicitly
set true before upgrading**. Disabled telemetry logs its reason and stops
the agent at startup, as required by current policy v2. An HTTP/network failure
never stops an activated PBS monitoring loop.

The telemetry service is `https://telemetry.digitalhouses.vip/v1/heartbeat`.
The JSON contains **only**: schema, telemetry policy version 2, persistent
random UUIDv4 installation ID, product `digitalhouses_pbs_agent` and released
agent version. The 256-bit authentication token is sent via Authorization
header and stored owner-only in `/var/lib/digitalhouses_pbs_agent/telemetry.json`
outside the repository. Country is derived server-side. No hostname, IP,
PBS datastore, snapshots, storage health, MQTT details or account data are
transmitted. Normal cadence is once per 24 hours ±30 minutes with a minimum
one-hour backoff after failure. The same UUID survives upgrades. Deleting an
installation and its retained server history is available via
`dh-pbs-agent telemetry-delete`, which rotates the local identity and
restarts only the agent so subsequent use reports a new installation.

Privacy terms: [DigitalHouses Product Telemetry Policy](../docs/standards/PRODUCT_TELEMETRY_POLICY.md).
Legal rollout remains subject to [Privacy / Legal Review](../docs/standards/TELEMETRY_PRIVACY_LEGAL_REVIEW.md);
public release cannot by itself establish consent or close that review.
