# DigitalHouses PBS Agent v0.1.2

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
DIGITALHOUSES_SOURCE_REF=digitalhouses_pbs_agent-v0.1.2 \
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
