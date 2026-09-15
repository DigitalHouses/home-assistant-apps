# DH PVE Runtime Observability Design

Date: 2026-09-15
Branch: `design/dh-pve-observability-ups-trigger-v2`
Depends on: PR #12 (`fix/dh-pve-nut-command-acl`, head `40f1121b5560a3832569cdfe777055b092c9b1be`)

## Purpose

Add production incident observability to `dh_pve_app` without creating a second logging subsystem or a high-volume log stream.

The 2026-09-15 UPS incident showed the gap: the host heated sharply while on battery, but the root cause had to be reconstructed with an external observer. The sustained load was a NUT/upssched CPU loop; `dh_pve_app` collectors contributed shorter CPU spikes. A normal production journal should have made that distinction obvious.

## Goals

- Show which collector/command consumed time around an incident.
- Correlate host pressure with `dh_pve_app.service` and `nut-monitor.service` CPU.
- Emit one compact performance/collector/command summary every 60 seconds at INFO.
- Log slow/failing operations without logging every successful poll.
- Keep per-operation success detail at DEBUG only.
- Persist a compact shutdown incident timeline and the active policy context across reboot.
- Use `journald` retention only; no custom log files, cron cleanup, logrotate config, or application ring buffer.
- Keep secrets out of logs.
- Make observability fail-open: an instrumentation failure must never affect monitoring or shutdown safety.

## Non-goals

- No monitoring database.
- No fast diagnostic MQTT entities.
- No Home Assistant logging knobs beyond the existing app log level.
- No storage dependency detection in this change.
- No destructive UPS/FSD test.

## Existing boundaries to preserve

- `DhPveRuntime._collect_one()` contains collector failures.
- Production collectors use command helpers such as `production._run()`.
- `TopologyManager` already accepts a runner dependency.
- systemd sends stdout/stderr to `journald`.
- `ShutdownHistoryTracker` persists reboot/shutdown history under `/var/lib/dh_pve_app`.

Observability augments these boundaries; it must not change collector cadence, MQTT publication policy, or NUT shutdown behavior.

## Logging model

### INFO

INFO contains only low-volume operational evidence:

- app startup/stop;
- meaningful MQTT/UPS transitions;
- one `PERF` line per 60 seconds;
- one `COLLECTORS` line per 60 seconds;
- one `COMMANDS` line per 60 seconds;
- shutdown timeline milestones;
- UPS trigger/FSD transitions once Trigger Policy v2 exists.

INFO must not contain every poll or every successful command.

### WARNING / ERROR

WARN/ERROR on:

- collector failure;
- recovery after collector failure;
- command failure/timeout;
- slow collector/command;
- inability to read performance accounting;
- inability to persist shutdown timeline state.

Repeated warning suppression rule:

- same logical key + same failure class: at most one WARNING per 60 seconds;
- recovery is always logged once when the operation becomes healthy again;
- a different failure class may log immediately.

### DEBUG

DEBUG may contain every collector/command duration and detailed decision information. DEBUG is off in normal production operation.

## Journald retention and disk safety

No application cleanup mechanism is added. `journald` remains responsible for retention/rotation/deletion.

The service explicitly limits bursts:

```ini
LogRateLimitIntervalSec=30s
LogRateLimitBurst=200
```

These values are a safety net, not a substitute for low-volume logging. `systemd-analyze verify` is part of the release gate.

## Runtime statistics accumulator

Create one process-local accumulator for the current 60-second summary window.

For each logical collector/command key record:

- count;
- total duration;
- maximum duration;
- failures;
- timeouts where applicable.

The window is reset only after the summary is emitted. The accumulator is not persisted and is not published to MQTT.

## Collector instrumentation

Instrument `DhPveRuntime._collect_one()` with monotonic timing around the existing call.

Behavior:

- record success/failure/duration;
- preserve `SubsystemState` semantics exactly;
- WARN only on failure, recovery, or slow duration;
- DEBUG may log every run;
- instrumentation exceptions are swallowed after a rate-limited warning and cannot fail the collector.

Slow collector thresholds for the first release:

| Collector | WARN at |
|---|---:|
| `cpu` | 1.0 s |
| `memory` | 1.0 s |
| `fans` | 1.0 s |
| `guests` | 2.0 s |
| `topology` | 2.0 s |
| `storage` | 2.0 s |
| `gpu` | 6.0 s |
| `smart` | 20.0 s |
| `host` | 5.0 s |

These thresholds are diagnostics only and never alter scheduling/profiles.

Example:

```text
COLLECTORS window=60s cpu=count:6 avg:0.012s max:0.018s fail:0 guests=count:2 avg:1.10s max:1.20s fail:0 gpu=count:2 avg:4.80s max:5.00s fail:0
```

## Instrumented external command runner

Introduce one reusable runner for production collectors/topology. It must preserve existing stdout/check/timeout behavior while adding monotonic timing and stable attribution.

Stable keys and first-release WARN thresholds:

| Key | WARN at |
|---|---:|
| `pvesh.cluster_resources` | 2.0 s |
| `qm.list` | 2.0 s |
| `pct.list` | 2.0 s |
| `qm.agent_ping` | 3.0 s |
| `qm.guest_exec.gpu` | 6.0 s |
| `qm.guest_exec.smart` | 20.0 s |
| `pvesm.status` | 2.0 s |
| `smartctl.scan` | 5.0 s |
| `smartctl.read` | 20.0 s |
| `lspci.inventory` | 2.0 s |
| `pveversion` | 2.0 s |
| `lscpu` | 2.0 s |

The runner records count/total/max/failure/timeout in the shared accumulator.

Do not log arbitrary argv blindly. Logging uses the stable logical key and sanitized metadata only; guest shell command bodies, NUT credentials, MQTT credentials and passwords are forbidden.

Known expensive paths must migrate to this runner in the first release: guest topology polling, GPU guest exec, guest SMART exec, storage, SMART and host inventory.

Example:

```text
COMMANDS window=60s pvesh.cluster_resources=count:2 total:2.20s max:1.20s fail:0 qm.guest_exec.gpu=count:2 total:9.70s max:5.00s fail:0 pvesm.status=count:1 total:0.80s max:0.80s fail:0
```

## Host/service performance summary

Every 60 seconds emit one compact `PERF` line.

Sources:

- host CPU delta: `/proc/stat`;
- load average: `/proc/loadavg`;
- CPU temperature: existing CPU temperature reader;
- App CPU delta: `/sys/fs/cgroup/system.slice/dh_pve_app.service/cpu.stat` (`usage_usec`);
- NUT monitor CPU delta: `/sys/fs/cgroup/system.slice/nut-monitor.service/cpu.stat` (`usage_usec`);
- App memory: `/sys/fs/cgroup/system.slice/dh_pve_app.service/memory.current`;
- UPS high-level state: the current in-process UPS snapshot when available.

Do not spawn `systemctl` every minute for accounting.

CPU values are interval deltas. Service CPU is expressed as `%core`: 100% means one logical core saturated over the 60-second window.

A missing cgroup/temperature/UPS field omits that field but does not suppress the rest of the summary.

Example:

```text
PERF window=60s host_cpu=42.1% temp=84C load1=1.89 app_cpu=8.3%core nut_cpu=99.1%core app_rss=214MiB ups=OB
```

## UPS decision audit contract

Runtime Observability defines the vocabulary used by UPS Trigger Policy v2:

```text
UPS_TRIGGER ON_BATTERY ...
UPS_TRIGGER ONLINE ...
UPS_TRIGGER LOW_BATTERY ...
UPS_TRIGGER RUNTIME_CONFIRM ...
UPS_TRIGGER FSD ...
UPS_TRIGGER CANCELLED ...
```

INFO logs transitions only, never every 5-second UPS poll.

Relevant fields may include charge, runtime, low-battery threshold, shutdown budget, reserve, effective runtime trigger, confirmation count, policy revision and final FSD reason.

## Durable shutdown incident timeline

Extend `ShutdownHistoryTracker`; do not create a parallel history subsystem.

Persist when observable:

- `outage_started_at`;
- `fsd_at`;
- `fsd_reason`;
- `host_shutdown_started_at`;
- `all_guests_stopped_at`;
- `last_shutdown_event_at`;
- `next_boot_at`.

Derived durations:

- `outage_to_fsd_seconds`;
- `fsd_to_shutdown_start_seconds`;
- `shutdown_start_to_guests_stopped_seconds`;
- `fsd_to_last_shutdown_event_seconds`;
- `host_offline_gap_seconds` (`last_shutdown_event_at -> next_boot_at`);
- `fsd_to_next_boot_seconds`.

`host_offline_gap_seconds` must never be described as exact UPS output-off duration. Physical UPS output-off/on instants are not known from host journal timestamps alone.

### Policy snapshot stored with the incident

Store factual policy context active at the incident:

- `policy_revision`;
- `battery_charge_low_percent` when known;
- `guest_shutdown_budget_seconds`;
- `total_shutdown_budget_seconds` when Policy v2 exists;
- `runtime_safety_reserve_seconds` when available;
- `effective_runtime_trigger_seconds` when available;
- `power_restore_delay_seconds`;
- relevant NUT role/state identifiers needed to explain the shutdown path.

Historical snapshots are immutable after later config changes.

Existing shutdown history remains canonical for clean/unclean result, shutdown reason, per-guest duration/result and total guest shutdown duration.

## MQTT / Home Assistant

Do not publish `PERF`, `COLLECTORS` or `COMMANDS` summaries to MQTT; doing so would recreate Recorder churn.

The existing shutdown-history group may gain incident fields, but only changes to the persisted incident cause publication.

No new fast diagnostic sensors are required.

## Error handling

Observability is fail-open:

- accumulator failure cannot stop a collector;
- cgroup/accounting failure cannot stop the runtime loop;
- formatting/logging failure cannot block MQTT publication;
- history persistence failure is logged but cannot interfere with NUT/PVE shutdown.

## Security

- Never log NUT/MQTT passwords or generated control credentials.
- Never log arbitrary guest command output at INFO.
- Preserve App/NUT privilege separation.

## Testing

Use TDD. Cover at least:

- collector duration success/failure;
- previous subsystem data preserved on collector failure;
- failure/recovery transition logging and 60-second warning suppression;
- command runner stdout/check/timeout compatibility;
- stable command attribution and sanitization;
- exact slow thresholds above;
- 60-second aggregation reset behavior;
- host/service CPU delta calculation from fixture `cpu.stat` and `/proc/stat` data;
- missing accounting fields tolerated;
- INFO summaries emitted once per 60 seconds, not per poll;
- DEBUG timing does not alter behavior;
- shutdown timeline duration calculations with timezone-aware timestamps;
- historical policy snapshot immutability;
- `host_offline_gap_seconds` semantics;
- all existing shutdown-history tests remain green;
- systemd unit verifies with `LogRateLimitIntervalSec=30s` and `LogRateLimitBurst=200`.

## Deployment validation

Non-destructive home-PVE validation:

1. deploy exact feature SHA;
2. wait two summary windows and verify one `PERF`, `COLLECTORS`, `COMMANDS` line per window;
3. verify `pvesh.cluster_resources` and GPU guest-exec are visible in command summaries;
4. verify App/NUT service CPU values are plausible under OL;
5. Manual Refresh must not create an INFO storm;
6. restart only `dh_pve_app.service`; no false PVE shutdown incident may appear;
7. confirm MQTT/Recorder behavior is unchanged.

No battery discharge, FSD, UPS output shutdown or destructive power-cycle test is part of this release gate.

## Technical debt out of scope

Track separately:

> Detect PVE NFS/CIFS/SMB storage whose provider is a VM/LXC/NAS participating in the same shutdown sequence. Warn that stopping the storage provider before host unmount can introduce long storage/unmount timeouts and make actual host shutdown exceed the calculated budget.
