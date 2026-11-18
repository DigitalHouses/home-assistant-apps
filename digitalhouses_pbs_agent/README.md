# DigitalHouses PBS Agent v0.1.0

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

The agent observes native PBS HTTPS API endpoints for the server version,
datastore status, snapshots and **push** sync, verify, prune and GC jobs,
plus local read-only zpool and filesystem status. It does not run or
edit PBS jobs, backup snapshots, PVE jobs, Plex, ZFS or retention.
A job appearing as OK is **not** proof of restore verification.

## HOME installation / release

**No production deployment before an immutable public release tag and live
acceptance on HOME PBS.** After the GitHub Release is published:

```bash
DIGITALHOUSES_SOURCE_REF=digitalhouses_pbs_agent-v0.1.0 \
  bash install.sh --non-interactive \
  --set mqtt_host=YOUR_MQTT_HOST \
  --set pbs_token_id='monitor@pbs!read' \
  --set pbs_datastores=pbs-home \
  --set pbs_insecure_localhost=true
```

Create a PBS read-only API token and store its secret securely at
`/etc/digitalhouses_pbs_agent/pbs.token` as root-readable 0600 **before
installation**. Provide the real local datastore(s) from PBS. The example
names above are illustrative; no HOME/CORE addresses, credentials or
datastore names are hard-coded into the product. Use `pbs_ca_file` to verify
the PBS TLS certificate; setting `pbs_insecure_localhost=true` is permitted
**only for a loopback API endpoint**.

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
url = https://127.0.0.1:8007
token_id = monitor@pbs!read
token_secret_file = /etc/digitalhouses_pbs_agent/pbs.token
ca_file =
insecure_localhost = true
datastores = pbs-home

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

An API failure is explicit; credentials need only PBS API **read permissions**
appropriate to the inventory endpoints. Never grant a write role to enable
monitoring. ZFS commands are read-only `zpool list`, no scrub/import/destroy.
Snapshots use PBS metadata, not archive contents or chunk scans.

## Acceptance gate before v0.1.0 release

1. On HOME PBS 4.x verify API token ACL and actual JSON shapes of
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
