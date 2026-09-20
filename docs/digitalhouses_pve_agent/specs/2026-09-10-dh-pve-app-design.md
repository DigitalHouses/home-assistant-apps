# DH PVE App — Design Specification

**Date:** 2026-09-10  
**Status:** Proposed for implementation  
**Application:** `dh_pve_app`  
**Type:** `linux_agent`

## 1. Purpose

`dh_pve_app` is a native Python monitoring agent for Proxmox VE hosts. It replaces the current one-shot Bash `digitalhouses-proxmox-mqtt.sh` implementation with a long-running, modular service while preserving the useful monitoring coverage and improving MQTT efficiency, disk-health diagnostics, Home Assistant recorder safety, and maintainability.

Phase 1 covers Proxmox monitoring only. UPS/NUT support is explicitly deferred to Phase 2, but the runtime architecture must allow an UPS module to be added later without restructuring the application.

The existing Bash implementation remains enabled during Phase 1 validation. Both systems may run simultaneously because the new Python application uses a different MQTT namespace, device identity, unique IDs, and Home Assistant entity IDs.

## 2. Application identity and installation layout

Application name:

```text
dh_pve_app
```

Canonical installation layout:

```text
/opt/digitalhouses/dh_pve_app/
/etc/dh_pve_app/dh_pve_app.conf
/var/lib/dh_pve_app/
```

Systemd unit:

```text
dh_pve_app.service
```

Home Assistant MQTT device name:

```text
DH PVE
```

Repository layout:

```text
dh_pve_app/
├── digitalhouses.app
├── README.md
├── CHANGELOG.md
├── VERSION
├── install.sh
├── requirements.txt
├── app/
├── systemd/
├── tests/
└── examples/
    └── dh_pve_app.conf.example
```

`digitalhouses.app` declares:

```text
type = linux_agent
```

## 3. MQTT namespace and Home Assistant identity

The MQTT base namespace is:

```text
DigitalHouses/Global/dh_pve_app
```

Each host gets a stable instance branch derived from the configured instance identity. The installer should auto-detect a sensible default from `/etc/machine-id`, but the effective value is represented in configuration and must remain stable after installation.

Recommended topic layout:

```text
DigitalHouses/Global/dh_pve_app/<instance>/state
DigitalHouses/Global/dh_pve_app/<instance>/availability
DigitalHouses/Global/dh_pve_app/<instance>/refresh
DigitalHouses/Global/dh_pve_app/<instance>/settings/...
DigitalHouses/Global/dh_pve_app/<instance>/manifest
```

MQTT Discovery remains enabled from first startup.

The Python application must not reuse old Bash entity unique IDs. New entities use the `dh_pve_` prefix and therefore can coexist safely with the old `digitalhouses_proxmox_*` entities during validation.

Examples:

```text
sensor.dh_pve_cpu_usage
sensor.dh_pve_memory_usage
sensor.dh_pve_cpu_temperature
sensor.dh_pve_cpu_frequency
sensor.dh_pve_storage_<id>_usage
sensor.dh_pve_disk_<id>_temperature
binary_sensor.dh_pve_disk_<id>_smart
sensor.dh_pve_disk_<id>_wear
sensor.dh_pve_disk_<id>_health
button.dh_pve_refresh
sensor.dh_pve_last_refresh
```

For multiple hosts in the same Home Assistant instance, entity IDs must remain collision-safe. The default single-host names above are preferred when possible, while the unique ID must always include the stable instance identity.

## 4. Runtime architecture

`dh_pve_app` is a long-running Python daemon managed by systemd.

The process uses one shared MQTT connection and an internal scheduler. Monitoring responsibilities are split into isolated collectors/modules with normalized outputs.

Initial logical structure:

```text
app/
├── app.py
├── config.py
├── models.py
├── mqtt_bridge.py
├── discovery.py
├── publish_policy.py
├── scheduler.py
├── state_store.py
└── collectors/
    ├── host.py
    ├── cpu.py
    ├── memory.py
    ├── storage.py
    ├── disks.py
    ├── smart.py
    ├── gpu.py
    └── cooling.py
```

The core must not contain hardware-specific parsing logic. Each collector owns collection and normalization for one subsystem. MQTT, Discovery, scheduling, persistence, and publish policy are shared infrastructure.

Phase 2 may add:

```text
collectors/ups.py
```

without changing the core architecture.

## 5. Polling and event-driven MQTT publication

Linux hardware metrics do not provide one reliable event stream for all required values, so collection remains periodic. MQTT state publication is event-driven relative to the last successfully published value.

Principle:

```text
poll → normalize → compare with last successfully published state
                 ↓
      insignificant change → no MQTT state publish
      significant change   → publish immediately
```

There is no periodic state heartbeat. Application liveness is represented by MQTT availability with Last Will and Testament (LWT). MQTT protocol keepalive is transport-level behavior and must not force state publications.

Initial polling and publish-delta defaults:

| Metric | Poll interval | Publish threshold |
|---|---:|---:|
| CPU usage | 10 s | 5 percentage points |
| RAM usage | 10 s | 1 percentage point |
| Swap usage | 10 s | 1 percentage point |
| CPU temperature | 10 s | 1 °C |
| CPU frequency | 10 s | 100 MHz |
| Fan RPM | 10 s | 100 RPM or 5%, whichever is meaningful |
| GPU load | 10 s | 5 percentage points |
| GPU temperature | 10 s | 1 °C |
| Disk temperature | 30 s | 1 °C |
| Storage usage | 60 s | 0.5 percentage points |
| SMART basic status | 60 s | any state change |
| SMART extended counters | 1 h | any counter change |
| Hardware inventory | 24 h | any inventory change |
| Daily disk-health snapshot | 24 h | scheduled daily snapshot |

Immediate publication is required for discrete events and transitions, including:

```text
host state change
SMART OK ↔ ERROR
CPU thermal throttling start/stop
disk/storage/GPU/fan appearance or disappearance
collector failure/recovery
disk health state change
manual refresh
MQTT reconnect requiring state restoration
```

The comparison baseline must be the last successfully published snapshot, not merely the last collected snapshot.

## 6. Manual refresh

Home Assistant exposes:

```text
button.dh_pve_refresh
sensor.dh_pve_last_refresh
```

The button publishes `PRESS` to:

```text
DigitalHouses/Global/dh_pve_app/<instance>/refresh
```

A refresh command triggers a full collection of all enabled Phase 1 collectors and forces a complete MQTT state publication regardless of publish deltas. `sensor.dh_pve_last_refresh` records the timestamp of the last successful manual full refresh.

This follows the existing DigitalHouses DB Monitoring / Plex Monitoring refresh pattern.

## 7. Home Assistant adjustable runtime settings

Operational tuning parameters may be changed from Home Assistant through MQTT Discovery `number`, `select`, or `switch` entities.

Suitable settings include:

```text
fast polling interval
disk polling interval
CPU publish delta
RAM/Swap publish delta
temperature publish delta
storage publish delta
fan publish delta
GPU-load publish delta
optional collector enable/disable where safe
```

Every setting has hard application-defined minimum and maximum limits. Invalid commands are rejected and the effective value is republished.

Runtime settings persist across application/host restarts under `/var/lib/dh_pve_app/`. They override configuration defaults until explicitly changed or reset.

Safety and health-policy parameters are not editable from Home Assistant. In particular, SMART health criteria, disk replacement thresholds, machine identity, MQTT credentials, and other security-sensitive parameters remain application/config controlled.

## 8. Configuration and autonomous installer

The application uses INI-style configuration:

```text
/etc/dh_pve_app/dh_pve_app.conf
```

The installer is intended to be usable through a single bootstrap command such as `curl | bash`.

Installer behavior:

1. Verify that the host is Proxmox VE.
2. Install required OS/runtime dependencies.
3. Install/update application code under `/opt/digitalhouses/dh_pve_app/`.
4. Preserve an existing valid configuration.
5. Auto-detect host identity where reliable, including `/etc/machine-id`, hostname, kernel, and Proxmox version.
6. If configuration is missing, ask only for mandatory values that cannot safely be inferred, especially MQTT connection parameters and optional display/node name.
7. If configuration exists but is invalid, report the exact invalid/missing setting instead of overwriting the file.
8. Print a copy/paste-friendly edit command and minimal configuration example, for example:

```text
nano /etc/dh_pve_app/dh_pve_app.conf
```

9. Validate configuration before starting the service.
10. Install and enable `dh_pve_app.service`.
11. Capture application version, Git source ref, and commit SHA in build metadata.
12. Start/restart service and report final status.

The installer must not disable, edit, or remove the existing Bash cron job during Phase 1 validation.

Secrets must never be committed to Git and should not be echoed back after initial entry.

## 9. Collector failure isolation and availability

A failure in one collector must not make unrelated entities unavailable.

Examples:

```text
SMART read fails for one disk → only that disk SMART data becomes unavailable
pvesm collection fails        → storage subsystem becomes unavailable
QEMU guest agent unavailable  → affected guest-derived GPU/SMART data unavailable
GPU collector fails           → GPU entities unavailable, CPU/storage remain valid
```

The application exposes diagnostic status for collector health and recovery.

Application process/MQTT liveness uses retained availability plus MQTT LWT:

```text
online
offline
```

No synthetic state heartbeat is required.

## 10. Existing Proxmox monitoring coverage

Phase 1 must preserve the useful monitoring capabilities of the Bash implementation, including where supported by the host:

```text
host identity/status/uptime
system model and board information
installed memory information
CPU usage and topology
CPU frequency and frequency limits
CPU temperature
CPU thermal throttling counters/events
RAM and swap usage
Proxmox storage usage
physical disk inventory
stable physical disk identity
SMART status/details
SSD/NVMe wear
physical disk assignment/passthrough
PCI storage-controller passthrough awareness
QEMU guest-agent SMART collection when required
GPU inventory and ownership
GPU temperature
Intel GPU transcoding load where available
fan RPM
thermal diagnostics
inventory disappearance/recovery handling
```

New Python entity IDs and payload organization may differ from the Bash implementation, but values and semantics must be comparable during parallel validation.

## 11. Stable hardware identity

Dynamic entities require stable object identifiers so device path changes do not create duplicate Home Assistant entities.

For physical disks, identity preference remains conceptually:

```text
WWN → serial → stable fallback
```

For GPUs, storage, fans, and other dynamic objects, collectors must define deterministic stable identifiers suitable for unique IDs and inventory reconciliation.

An object is not deleted immediately after one failed scan. Missing-object confirmation and collector-authority rules must distinguish a true hardware removal from a failed collection.

## 12. Disk health model

The Python application, not Home Assistant templates, computes disk health.

The user-facing disk-health state is intentionally limited to three levels:

```text
HEALTHY
WARNING
CRITICAL
```

Meanings:

- `HEALTHY`: no relevant degradation detected.
- `WARNING`: degradation or lifetime indicators justify administrative attention and potentially planning a replacement, but the disk is not yet considered an active critical failure.
- `CRITICAL`: an active or strongly indicated failure condition requires prompt intervention.

The state includes compact explanatory attributes such as:

```text
reason
recommendation
wear_used_percent
power_on_hours
max_temperature_24h
media_errors
reallocated_sectors
pending_sectors
unsafe_shutdowns
data_written_tb
```

Health thresholds are built into the versioned application logic, not editable through Home Assistant or normal site configuration. This prevents unsafe per-site tuning and gives all installations the same known policy.

Initial policy should consider at least:

```text
SMART overall failure
NVMe critical_warning
wear/lifetime used
media errors
reallocated sectors
pending sectors
offline/uncorrectable errors
unsafe shutdown counter growth
power-on hours as a planning signal
sustained/high daily maximum temperature
counter growth over time
```

Power-on hours alone must not normally make a disk `CRITICAL`; it is a planning signal that should be interpreted with other health indicators.

## 13. Daily disk-health history

The application maintains local daily disk statistics so Home Assistant does not need template sensors to calculate them.

For each supported physical disk, publish compact history-friendly entities for values such as:

```text
SMART status
power-on hours
maximum temperature during the day
wear used percent
media errors
reallocated sectors
pending sectors
unsafe shutdowns
data written
health state
```

Continuous temperature remains a normal metric. Daily maximum temperature is accumulated by the Python agent and published as a daily summary.

These entities are designed to be cheap for Home Assistant Recorder: small numeric/state values with minimal attributes and low change frequency.

Home Assistant controls the actual Recorder retention period. The current site package is expected to keep Proxmox history according to its configured 30–100 day policy; the application must not hard-code a Recorder retention period.

## 14. Recorder-safe entity design

Home Assistant historical entities must not carry large volatile diagnostic attribute objects.

Historical entities contain only the attributes needed for identification and UI rendering. Examples include:

```text
proxmox_integration
proxmox_section
proxmox_subject
proxmox_metric
proxmox_object_id
proxmox_display_name
model
disk_type
```

Large SMART details, inventory structures, scan timestamps, `last_seen`, event arrays, and nested diagnostic objects must not be duplicated across frequently recorded measurement entities.

Rich diagnostic entities may expose detailed current attributes when useful for UI/notifications, but the Home Assistant package should exclude those entities from Recorder unless a specific historical need exists.

Home Assistant templates must not perform the primary disk-health or daily-statistics calculations.

## 15. Home Assistant semantic metadata

The new entities continue to expose semantic attributes suitable for `auto-entities` dashboards:

```text
proxmox_integration: dh_pve_app
proxmox_section
proxmox_subject
proxmox_metric
proxmox_object_id
proxmox_display_name
proxmox_sort_key
```

This keeps the existing dashboard architecture practical while allowing the new app to use shorter `dh_pve_*` entity IDs.

## 16. Notification architecture boundary

Phase 1 does not rewrite the Home Assistant notification package as part of the initial Python parity implementation.

The new entity model must, however, preserve enough current diagnostic information to support a later notification redesign.

Future routing is intentionally split:

```text
write2log     → short client-facing operational messages
write2admins  → detailed technical/admin messages
```

Proxmox infrastructure events are primarily administrative. SMART degradation, disk replacement planning, CPU throttling, detailed thermal problems, collector failures, and similar events should preferentially feed `write2admins`.

Critical events may also produce a concise client-facing `write2log` notification where useful. Repeated technical reminders, such as persistent SMART failures, belong to administrators rather than the client channel.

## 17. Parallel validation against Bash

During Phase 1 validation:

```text
Bash:
DigitalHouses/System/Proxmox/...
sensor.digitalhouses_proxmox_...

Python:
DigitalHouses/Global/dh_pve_app/...
sensor.dh_pve_...
```

Both remain operational at the same time.

The existing cron entry is left untouched:

```text
* * * * * root /usr/bin/flock -n /run/lock/digitalhouses-proxmox-mqtt.lock /root/digitalhouses-proxmox-mqtt.sh
```

The validation objective is to compare Bash and Python values and behavior for CPU, memory, storage, disks, SMART, GPU, fans, throttling, passthrough, and inventory handling.

Manual `button.dh_pve_refresh` provides an immediate Python snapshot for side-by-side comparison.

Only after the Python implementation has been validated will the old Bash scheduling and retained MQTT topics be retired in a separate controlled step.

## 18. Persistence

Local application state under `/var/lib/dh_pve_app/` may contain:

```text
runtime setting overrides
last successful published baseline
dynamic inventory/missing confirmation state
daily disk temperature accumulator
disk health trend/counter checkpoints
build/runtime metadata where appropriate
```

Persistence must survive service and host restarts safely. Corrupt state must not silently erase important health history or inventory state; the application should detect invalid persisted data, log a clear error, and recover conservatively.

## 19. Logging

Operational logs go to journald through systemd.

Logs should be concise, operator-oriented, and in Russian where messages are intended for the site administrator. Technical identifiers and command names remain unchanged when translation would reduce diagnostic value.

Normal polling with no publish-worthy change must not generate noisy logs.

## 20. Security and privilege model

The service may require root privileges because Proxmox monitoring uses privileged local interfaces and hardware inspection such as SMART, `/etc/pve`, QEMU/LXC configuration, passthrough information, and future local NUT configuration.

If root is used, the reason must be explicitly documented. Avoid complicated partial-sudo/capability workarounds unless they provide a clear security benefit without breaking reliable monitoring.

MQTT commands in Phase 1 are limited to safe monitoring operations such as refresh and bounded runtime tuning. They must not expose host shutdown, arbitrary command execution, file writes, or other administrative control paths.

## 21. Testing and repository contract

The application requires its own compatibility validator and CI job.

Minimum automated coverage:

```text
config parsing and validation
MQTT topic construction
Discovery device identity and entity IDs
refresh button contract
runtime setting command bounds and persistence
publish-policy thresholds
last-successful-publish baseline behavior
collector failure isolation
dynamic inventory reconciliation
stable disk identity
SMART parsing fixtures
GPU/fan/storage parsing fixtures
disk health HEALTHY/WARNING/CRITICAL rules
daily maximum temperature accumulation
Recorder-safe attribute contracts
installer shell syntax
Python compile/unit tests
systemd-analyze verify
```

Tests should include captured/normalized fixtures representative of the current `shahristan` Proxmox host and important edge cases from the Bash implementation.

## 22. Phase 2 boundary: UPS/NUT

UPS/NUT is not implemented in Phase 1.

The future target architecture remains:

```text
UPS → USB → Proxmox → NUT server/upsmon PRIMARY
                         ├─ local emergency shutdown policy
                         └─ dh_pve_app UPS collector → MQTT → HA
```

Proxmox/NUT remains the sole authority for emergency shutdown. Home Assistant is monitoring/UI/notification only and is never required for safe shutdown.

The UPS module may later create a separate Home Assistant MQTT device such as `DH UPS` while sharing the same Python process, scheduler, MQTT connection, configuration framework, and persistence infrastructure.

## 23. Phase 1 acceptance criteria

Phase 1 is ready to replace Bash only when all of the following are true:

1. `dh_pve_app` installs and upgrades autonomously on Proxmox VE.
2. It runs continuously under systemd and reconnects to MQTT cleanly.
3. MQTT Discovery creates a separate `DH PVE` device with stable `dh_pve_*` entities.
4. `button.dh_pve_refresh` performs a forced full refresh.
5. CPU/RAM/Swap/storage/temperature/frequency/GPU/fan metrics match the Bash implementation within expected sampling differences.
6. Physical disks and passthrough assignments are discovered correctly.
7. SMART data and disk health work for supported HDD/SSD/NVMe devices.
8. Event-driven publish suppression materially reduces MQTT writes compared with the current one-shot-per-minute Bash implementation.
9. No periodic state heartbeat is required; MQTT LWT correctly represents app connectivity.
10. Collector failures do not incorrectly make unrelated data unavailable.
11. Recorder-oriented entities contain compact attributes and do not duplicate large volatile diagnostic objects.
12. Daily disk-health metrics are produced without Home Assistant template calculations.
13. Runtime tuning from Home Assistant is bounded, validated, and persistent.
14. Old Bash and new Python application can run simultaneously without MQTT Discovery or entity-ID conflicts.
15. Repository validation, app-specific tests, and CI pass.

After these criteria are verified on the `shahristan` host, retiring the Bash implementation and redesigning the Home Assistant Recorder/notification packages are separate follow-up steps.