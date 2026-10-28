# DigitalHouses PVE Agent · Diagnostic event coverage audit

Date: 2026-10-29
Scope: PVE Agent repository events, Home Assistant handler example contracts and read-only inspection of the installed HAOS notification package. No production configuration changed.

## Findings

| Source / signal | Current machine event | Notification handler | Follow-up |
| --- | --- | --- | --- |
| CPU temperature, CPU throttling | Start/recovery semantic events | Existing | Keep |
| Storage utilization | High/normal | Existing | Keep |
| Disk temperature and GPU temperature | High/normal | Existing | Keep |
| Disk SMART overall pass/fail | Failed/restored | Existing | Keep |
| NFS service failures and recovery | Unavailable/restored | Existing | Keep |
| Fan control restore failure/recovery | Failure/restored | Existing | Keep |
| UPS/NUT availability, power states, alarm, discharge, software shutdown | UPS diagnostic event channel | Existing | Keep |
| SMART unsafe shutdown counter | No event before 0.5.71 | No live handler before 0.5.71 | Implemented in this PR |
| Backup/vzdump task completion/failure | No general semantic event | Missing | High-priority follow-up |
| Other SMART error counter growth (reallocated/pending/media errors) | SMART health WARNING/CRITICAL only, not a dedicated growth Event | Missing | Candidate, prioritise nonzero delta not every reading |
| Persistently blocked NFS I/O processes | No general semantic event | Missing | Candidate for dedicated health observer, avoid process-by-process spam |
| Generic in-flight Proxmox tasks | Native Proxmox task API, not a PVE Agent event contract | Missing | Separate UI feature: active tasks, not a notification for every task |

The actual HAOS installation has 48 event trigger/handler branches in
`packages/Global/DH_APP/dh_pve_agent_notification_package.yaml`. The source package
contains handlers for CPU, disk, GPU, NFS and UPS, but no `disk_unsafe_shutdowns_increased`
handler. It is **not** the same path as the maintained `write2admins` example. Editing
the example does **not** install a handler on the actual HA site.

## v0.5.71 contract

- PVE event: `disk_unsafe_shutdowns_increased`, emitted for existing SMART disk identity only when `unsafe_shutdowns` strictly increases.
- Payload: schema_version 2, event_type, event_id, observed_at, category, severity, object_id, object_name, metric, previous_value, current_value, delta, disk_type, device_path, cause=unknown; optional VM source metadata.
- First observation, unsupported/unavailable data, unchanged reading, and counter reset do not emit the event.
- Event detection is at existing SMART/HEALTH cadence, ordinarily hourly. `observed_at` is detection time, not necessarily shutdown time.
- SMART checkpoint and event outbox are stored atomically in `disks.json`; event delivery uses existing non-retained QoS1 PVE Diagnostic MQTT channel.
- Outbox is at-least-once, not exactly-once; handlers can use `event_id` to deduplicate a replay after a crash.
- Broker publish acknowledgement is **not** confirmation that Home Assistant processed the event. If HA is offline while MQTT broker is online, HA may not receive the transient event.
- No UPS required, no power-loss cause guessed. No change to NUT/shutdown decision or polling intervals.

## Next iteration

1. Expose active PVE tasks (read-only task API) in a dashboard card. Avoid VNC console tasks and only claim progress when genuinely available.
2. Emit semantic `backup_job_failed` / `backup_job_completed` with job ID, affected guest IDs and summary. A job may complete with errors even after some guests succeed.
3. Consider isolated counter-growth events for important SMART media errors, with event-level deduplication, and diagnose persistent blocked I/O independently from current NFS availability.
4. Make the HA notification handler matrix explicit per site; install/select exactly one notification package, do not overwrite custom admin routing during agent updates.

## Scope boundary

This PR adds the one approved SMART counter event and updates maintained examples. It does not deploy HA YAML or send test events to real user notification channels.
