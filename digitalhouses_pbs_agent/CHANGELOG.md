# DigitalHouses PBS Agent

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
