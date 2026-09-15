# DH PVE Runtime Observability Design

Date: 2026-09-15
Branch: `design/dh-pve-observability-ups-trigger-v2`
Depends on: PR #12 (`fix/dh-pve-nut-command-acl`, head `40f1121b5560a3832569cdfe777055b092c9b1be`)

## Purpose

Add production-grade incident observability to `dh_pve_app` without turning the application into a high-volume logger or adding a second log-storage subsystem.

The design is driven by the 2026-09-15 UPS incident, where the host heated sharply while on battery and the cause had to be reconstructed with an external observer. The eventual root cause was a NUT/upssched CPU loop, while `dh_pve_app` collectors contributed shorter CPU spikes. The application should provide enough evidence in its normal journal to distinguish these cases during the next incident.

## Goals

- Make it possible to answer, from the normal system journal, which subsystem consumed time and CPU around an incident.
- Measure collector duration and failure/recovery without changing collector semantics.
- Measure important external command duration because commands such as `pvesh`, `qm guest exec`, `pvesm`, and `smartctl` can dominate collector cost.
- Record one compact performance summary per minute at INFO level.
- Record warnings for slow, failed, and timed-out operations.
- Keep detailed per-operation success logging at DEBUG level only.
- Add a durable shutdown incident timeline that survives reboot and records the policy context active during that shutdown.
- Keep disk usage bounded by existing `journald` retention; do not create custom log files, custom rotation, cron cleanup, or application-owned ring buffers.
- Keep secrets out of logs.
- Preserve monitoring and shutdown safety if observability itself fails.

## Non-goals

- No new monitoring database.
- No custom log daemon or JSONL file storage.
- No per-sample telemetry log at INFO.
- No Home Assistant control for log verbosity beyond the existing application log-level mechanism.
- No automatic storage dependency detection in this change.
- No destructive UPS/FSD testing.

## Existing architecture

`dh_pve_app` already has useful isolation boundaries:

- `DhPveRuntime._collect_one()` executes each collector and contains collector failures.
- production collectors call shared command helpers such as `production._run()`.
- `TopologyManager` accepts a runner dependency and therefore can be instrumented without coupling topology logic to logging.
- systemd already owns stdout/stderr through `journald`.
- `ShutdownHistoryTracker` persists reboot/shutdown history under `/var/lib/dh_pve_app`.

The current gaps are:

- `_collect_one()` does not measure or log collector duration;
- many external command calls are not timed or attributed in a common way;
- some expected collector exceptions are intentionally swallowed, making slow/failing internal operations invisible;
- no compact periodic summary correlates host pressure with application/NUT service CPU;
- shutdown history records outcome, but not a complete incident timeline and policy snapshot suitable for forensic review.

## Logging model

Use the existing Python logging pipeline and `journald` only.

### INFO

INFO is for low-volume operational evidence:

- app startup and clean stop;
- MQTT connection/recovery transitions already useful operationally;
- UPS state transitions relevant to shutdown decisions;
- one aggregated `PERF` summary per 60 seconds;
- one aggregated `COLLECTORS` summary per 60 seconds;
- one aggregated `COMMANDS` summary per 60 seconds;
- shutdown timeline milestones;
- policy revision applied during a shutdown incident.

INFO must not log every collector run or every successful external command.

### WARNING / ERROR

Warn on:

- collector failure;
- collector recovery after failure;
- collector duration above its slow-operation threshold;
- command non-zero exit when unexpected;
- command timeout;
- command duration above its slow-operation threshold;
- inability to read performance accounting;
- inability to persist shutdown timeline state.

Repeated identical warnings must be rate-limited or transition-based so a single broken subsystem cannot flood the journal.

### DEBUG

DEBUG may contain:

- each collector start/end with duration;
- each instrumented external command with duration and result category;
- detailed presentation/router decisions when needed;
- runtime-trigger evaluation detail once UPS Trigger Policy v2 exists.

DEBUG is off in normal production operation.

## Journald retention and disk safety

No application-owned cleanup logic is added.

`dh_pve_app` writes to stdout/stderr as it does today; systemd/journald remains responsible for retention, rotation, and deletion of old logs according to host policy.

The application must reduce volume at the source:

- summaries once per 60 seconds;
- event/transition logging instead of repeated state logging;
- per-operation success details only at DEBUG;
- repeated warnings de-duplicated or rate-limited.

The systemd unit should explicitly use sensible journald rate limiting so a software defect cannot emit unbounded lines in a short interval. The implementation must use systemd-supported service rate-limit directives appropriate for the target Debian/systemd version and verify them with `systemd-analyze verify`.

## Instrumentation components

### 1. Operation statistics accumulator

Introduce a small process-local accumulator responsible only for aggregated runtime statistics.

For each collector and command key it tracks the current summary window:

- count;
- total duration;
- maximum duration;
- failures;
- timeouts where applicable.

The accumulator resets after the periodic summary is emitted.

It is not persisted across restarts and is not published to MQTT.

### 2. Collector instrumentation

Instrument `DhPveRuntime._collect_one()` around the existing collector call.

For each collector run:

- measure monotonic elapsed time;
- record success/failure in the accumulator;
- preserve the existing `SubsystemState` behavior exactly;
- WARN only on failure, recovery, or an abnormal duration;
- DEBUG may show every duration.

Collector instrumentation must not change scheduling or publication decisions.

Example summary:

```text
COLLECTORS window=60s cpu=count:6 avg:0.012s max:0.018s fail:0 memory=count:6 avg:0.004s max:0.006s fail:0 guests=count:2 avg:1.10s max:1.20s fail:0 gpu=count:2 avg:4.80s max:5.00s fail:0
```

Formatting can be compact, but the field names and collector identity must be stable enough for grep/journal analysis.

### 3. Instrumented external command runner

Create one reusable runner abstraction for commands executed by production collectors/topology.

Responsibilities:

- execute a command with existing timeout/check semantics;
- measure monotonic duration;
- attribute the command to a stable logical key;
- record count/total/max/failure/timeout in the accumulator;
- sanitize arguments before logging;
- preserve stdout and exception semantics expected by callers.

Stable logical keys are preferred over full argv. Examples:

- `pvesh.cluster_resources`
- `qm.list`
- `pct.list`
- `qm.agent_ping`
- `qm.guest_exec.gpu`
- `qm.guest_exec.smart`
- `pvesm.status`
- `smartctl.scan`
- `smartctl.read`
- `lspci.inventory`

The command runner must not log credentials, MQTT passwords, NUT command passwords, or arbitrary guest command contents that can contain sensitive data.

The migration should be incremental but complete for the known expensive paths involved in incident analysis: topology guest polling, GPU guest exec, storage, SMART, and host inventory commands.

Example summary:

```text
COMMANDS window=60s pvesh.cluster_resources=count:2 total:2.20s max:1.20s fail:0 qm.guest_exec.gpu=count:2 total:9.70s max:5.00s fail:0 pvesm.status=count:1 total:0.80s max:0.80s fail:0
```

### 4. Host/service performance summary

Every 60 seconds emit one compact `PERF` line.

Target fields:

- host aggregate CPU percentage;
- CPU temperature when available;
- load average;
- `dh_pve_app.service` CPU consumption from cgroup/systemd accounting;
- `nut-monitor.service` CPU consumption from cgroup/systemd accounting;
- application RSS if cheaply available;
- current UPS high-level state when a UPS is selected (`OL`, `OB`, `LB`, `FSD`-relevant state or normalized equivalent).

The exact source may use cgroup v2 files and `/proc` directly rather than spawning `systemctl` every minute, as long as it is reliable on PVE 8 / Debian 12.

The metrics should represent a window/delta where meaningful, not lifetime CPU percentages mislabeled as current load.

A failure to read one field must not fail the summary or the application; emit the remaining fields and rate-limit a warning.

Example:

```text
PERF window=60s host_cpu=42.1% temp=84C load1=1.89 app_cpu=8.3%core nut_cpu=99.1%core app_rss=214MiB ups=OB
```

`%core` means percentage of one logical CPU core, so `100%core` is approximately one saturated logical core regardless of host CPU count.

## Slow-operation policy

Use internal engineering defaults, not Home Assistant knobs.

The initial implementation may define conservative thresholds by command/collector class, for example:

- fast in-process collectors: warning at >= 1 second;
- topology/storage API calls: warning at >= 2 seconds;
- guest GPU exec: warning at >= 6 seconds;
- SMART reads: warning near their normal timeout budget rather than a universal low threshold.

These thresholds are for diagnostics only. They do not change collector scheduling or profiles.

A later tuning pass may adjust them from production evidence without changing any public contract.

## UPS decision audit contract

Runtime Observability must define a stable logging vocabulary used by the later UPS Trigger Policy v2 implementation.

Required event families:

```text
UPS_TRIGGER ON_BATTERY ...
UPS_TRIGGER ONLINE ...
UPS_TRIGGER LOW_BATTERY ...
UPS_TRIGGER RUNTIME_CONFIRM ...
UPS_TRIGGER FSD ...
UPS_TRIGGER CANCELLED ...
```

Each line should include only the values relevant to the decision, such as:

- charge percentage;
- runtime seconds;
- configured low-battery threshold;
- shutdown budget;
- safety reserve;
- effective runtime trigger;
- confirmation count;
- policy revision;
- final FSD reason.

Do not log every UPS poll at INFO.

## Durable shutdown incident timeline

Extend shutdown history with a compact persisted incident record that survives the power cycle.

Required timestamps when observable:

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
- `host_offline_gap_seconds` = `last_shutdown_event_at -> next_boot_at`;
- `fsd_to_next_boot_seconds`.

The application must not label `host_offline_gap_seconds` as exact UPS output-off duration. The exact physical output-off/output-on instants are not known unless the UPS exposes them independently.

### Policy snapshot stored with the incident

Persist the active policy context used for the incident:

- `policy_revision`;
- `battery_charge_low_percent` when known;
- `guest_shutdown_budget_seconds`;
- `total_shutdown_budget_seconds` when UPS Trigger Policy v2 is implemented;
- `runtime_safety_reserve_seconds` when available;
- `effective_runtime_trigger_seconds` when available;
- `power_restore_delay_seconds`;
- relevant NUT role/state identifiers needed to explain the shutdown path.

The snapshot is factual history. Later configuration changes must not rewrite old incident records.

## Relationship to current ShutdownHistoryTracker

Do not build a parallel history subsystem.

Extend `ShutdownHistoryTracker` so the existing previous-shutdown record remains the canonical source for:

- clean/unclean result;
- shutdown reason;
- per-guest shutdown durations and timeout results;
- total guest shutdown duration;
- the new incident timeline/policy snapshot.

Existing published history limits remain bounded.

## MQTT / Home Assistant surface

This observability change is primarily journal/history work.

Do not expose the minute-by-minute PERF/COLLECTORS/COMMANDS summaries to MQTT; that would recreate Recorder churn.

The existing shutdown-history MQTT group may gain stable incident fields needed by the dashboard or notifications, but only when the incident record changes.

No new fast telemetry entities are required.

## Error handling

Observability must be fail-open with respect to monitoring and safety:

- accumulator failure must not stop a collector;
- cgroup/accounting failure must not stop the runtime loop;
- logging-format failure must not block MQTT publication;
- shutdown-history persistence failure must be logged but must not interfere with NUT/Proxmox shutdown behavior.

## Security and privacy

- Never log NUT passwords, MQTT passwords, or generated control credentials.
- Sanitize external command logging.
- Do not log arbitrary guest command output at INFO.
- Keep existing App/NUT privilege separation unchanged.

## Testing

Use TDD.

Tests must cover at least:

- collector timing recorded on success;
- collector timing/failure recorded on exception while preserving previous subsystem data;
- failure/recovery warnings are transition-based and do not flood;
- command runner preserves stdout/check/timeout behavior;
- command timing statistics are attributed to stable keys;
- command arguments are sanitized;
- periodic summaries reset the current aggregation window correctly;
- performance accounting tolerates missing cgroup files/temperature/UPS fields;
- INFO summaries are emitted at the requested interval rather than on every poll;
- DEBUG can include per-operation timing without changing behavior;
- shutdown timeline derives durations correctly across timezone-aware timestamps;
- previous incident policy snapshot is immutable after later policy changes;
- `host_offline_gap_seconds` is named/represented without claiming exact UPS output-off duration;
- existing shutdown history parsing and classification tests remain green;
- systemd unit verification passes with any journald rate-limit directives added.

## Deployment validation

Production validation on the home PVE must be non-destructive.

Validate:

1. deploy exact feature SHA;
2. confirm normal `journalctl -u dh_pve_app.service` volume is low;
3. wait at least two summary windows and verify `PERF`, `COLLECTORS`, and `COMMANDS` appear once per window;
4. verify known expensive operations (`pvesh.cluster_resources`, GPU guest exec) are visible in aggregated command timing;
5. verify `dh_pve_app` and `nut-monitor` accounting values are plausible under normal OL operation;
6. run Manual Refresh and confirm it does not create an INFO log storm;
7. restart only `dh_pve_app.service` and verify no false PVE shutdown incident is created;
8. confirm MQTT/Recorder behavior remains unchanged.

No battery discharge, FSD, UPS output shutdown, or destructive power-cycle test is required for this observability release.

## Technical debt explicitly out of scope

Track separately:

> Detect PVE NFS/CIFS/SMB storage whose provider is a VM/LXC/NAS participating in the same shutdown sequence. Warn that stopping the storage provider before host unmount can introduce long storage/unmount timeouts and make actual host shutdown exceed the calculated budget.

This dependency detection must not delay Runtime Observability.