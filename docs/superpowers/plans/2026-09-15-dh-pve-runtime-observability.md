# DH PVE Runtime Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add low-volume production observability to `dh_pve_app` so a future CPU/UPS incident can be reconstructed from `journald`, including collector/command cost, host/service CPU, and a durable shutdown timeline.

**Architecture:** Keep normal stdout/stderr -> systemd/journald. Add in-process 60-second aggregation for collector/command timings, an injected instrumented command runner, and a `/proc`/cgroup-v2 performance sampler. Extend the existing `ShutdownHistoryTracker`; do not create a second history database or a separate log file.

**Tech Stack:** Python 3.13 in CI, pytest, Debian 12 / Proxmox VE 8 runtime, systemd 252, journald, cgroup v2, existing JSON `StateStore`.

**Spec:** `docs/superpowers/specs/2026-09-15-dh-pve-runtime-observability-design.md`

## Global Constraints

- Normal production logging stays in `journald`; do not add application-owned `.log`, JSONL, ring-buffer, cron cleanup, or global `journalctl --vacuum-*` logic.
- INFO performance summaries are emitted once per **60 seconds**.
- Per-operation successful timings are DEBUG only; DEBUG remains off by default.
- Repeated warnings are transition/rate based; no poll-by-poll INFO/WARNING storm.
- `dh_pve_app.service` log rate limit is **200 messages per 30 seconds**.
- Observability failure must never stop a collector, MQTT publication, UPS handling, or host shutdown.
- Do not publish minute PERF/COLLECTORS/COMMANDS summaries to MQTT/HA.
- Never log MQTT/NUT passwords, arbitrary guest command output, or unsanitized command arguments.
- Existing collector scheduling, adaptive publication profiles, averaging, and Recorder behavior must remain unchanged.
- Shutdown history remains bounded by the existing `HISTORY_LIMIT=50` and `PUBLISHED_HISTORY_LIMIT=10` contracts.
- `host_offline_gap_seconds` is only `last_shutdown_event_at -> next_boot_at`; never label it as exact UPS output-off duration.
- No battery discharge, FSD, UPS output shutdown, or destructive power-cycle test is part of this plan.
- Operational log messages remain in Russian where the surrounding module already logs in Russian; stable machine-searchable prefixes are English uppercase tokens (`PERF`, `COLLECTORS`, `COMMANDS`, `UPS_TRIGGER`).

---

## File Structure

### New files

- `dh_pve_app/app/observability.py` — timing aggregation, collector transition/slow warnings, 60-second summary formatting.
- `dh_pve_app/app/command_runner.py` — one sanitized, instrumented subprocess runner used by production collectors/topology.
- `dh_pve_app/app/performance.py` — `/proc` + cgroup-v2 delta sampler for host/app/NUT CPU, load, RSS and temperature input.
- `dh_pve_app/tests/test_observability.py` — aggregation/summary/rate behavior.
- `dh_pve_app/tests/test_command_runner.py` — command timing, timeout/failure semantics, sanitization.
- `dh_pve_app/tests/test_performance.py` — deterministic `/proc`/cgroup delta sampling.

### Existing files modified

- `dh_pve_app/app/app.py` — instrument `_collect_one()` without changing collector result semantics.
- `dh_pve_app/app/production.py` — inject runner; remove direct production use of module-global uninstrumented `_run()`.
- `dh_pve_app/app/production_guest.py` — route guest GPU/SMART exec paths through injected runner.
- `dh_pve_app/app/topology.py` — keep current runner seam but use stable instrumented command keys.
- `dh_pve_app/app/main.py` — construct observer/runner/performance sampler; emit summaries from main loop.
- `dh_pve_app/app/shutdown_history.py` — persist incident timeline, derived durations and policy snapshot.
- `dh_pve_app/app/shutdown_integration.py` — feed the active/effective shutdown policy snapshot into the canonical tracker.
- `dh_pve_app/app/shutdown_discovery.py` — expose stable incident fields only when shutdown history changes.
- `dh_pve_app/systemd/dh_pve_app.service` — per-unit journal rate limit.
- `dh_pve_app/tests/test_app_runtime.py` — collector timing/failure/recovery contract.
- `dh_pve_app/tests/test_topology.py`, `test_gpu.py`, `test_smart.py`, `test_storage.py`, `test_production_v1.py` — preserve command/collector behavior after runner injection.
- `dh_pve_app/tests/test_shutdown_history.py` — new persisted timeline/policy snapshot contract.
- `dh_pve_app/tests/test_shutdown_group_contract.py` and/or `test_shutdown_card_contract.py` — published incident fields remain stable.
- `dh_pve_app/tests/test_main_contract.py` — wiring and summary cadence contract.
- `dh_pve_app/README.md`, `dh_pve_app/CHANGELOG.md` — document the observability contract.

---

### Task 1: Add the aggregation core

**Files:**
- Create: `dh_pve_app/app/observability.py`
- Create: `dh_pve_app/tests/test_observability.py`

**Interfaces:**
- Produces: `OperationStats`, `OperationAccumulator.record()`, `OperationAccumulator.drain()`, `RuntimeObserver.record_collector()`, `RuntimeObserver.record_command()`, `RuntimeObserver.maybe_log_summaries()`.
- Consumes later: collector instrumentation, command runner, main-loop 60-second summary.

- [ ] **Step 1: Write failing aggregation tests**

Create tests with a fake logger and injected monotonic clock. Cover count, total, max, failures, timeouts and drain/reset:

```python
from app.observability import OperationAccumulator


def test_operation_accumulator_records_and_drains_window():
    acc = OperationAccumulator()
    acc.record("gpu", 4.0, success=True)
    acc.record("gpu", 5.0, success=False, timeout=True)

    window = acc.drain()

    assert window["gpu"].count == 2
    assert window["gpu"].total_seconds == 9.0
    assert window["gpu"].max_seconds == 5.0
    assert window["gpu"].failures == 1
    assert window["gpu"].timeouts == 1
    assert acc.drain() == {}
```

Add a summary-cadence test asserting no INFO output before 60 seconds and exactly one `COLLECTORS` plus one `COMMANDS` line at/after 60 seconds.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
cd dh_pve_app
PYTHONPATH=. python -m pytest tests/test_observability.py -q
```

Expected: import failure because `app.observability` does not exist.

- [ ] **Step 3: Implement the minimal aggregation model**

Use a focused immutable snapshot and a mutable accumulator:

```python
@dataclass(frozen=True)
class OperationStats:
    count: int
    total_seconds: float
    max_seconds: float
    failures: int
    timeouts: int


class OperationAccumulator:
    def record(self, key: str, duration_seconds: float, *, success: bool, timeout: bool = False) -> None: ...
    def drain(self) -> dict[str, OperationStats]: ...
```

`RuntimeObserver` owns separate collector and command accumulators and the last-summary monotonic timestamp. Formatting must use stable keys and must not emit empty per-operation DEBUG lines at INFO.

- [ ] **Step 4: Add slow/transition warning tests**

Cover these exact cases:

```python
observer.record_collector("smart", 2.0, success=False, error_type="RuntimeError")
observer.record_collector("smart", 0.5, success=False, error_type="RuntimeError")
observer.record_collector("smart", 0.5, success=True)
```

Assert one failure warning, no duplicate failure warning for the second identical failed state, and one recovery INFO/WARNING transition when it becomes healthy.

Use internal defaults in the module, not HA settings:

```python
COLLECTOR_SLOW_SECONDS = {
    "cpu": 1.0,
    "memory": 1.0,
    "fans": 1.0,
    "guests": 2.0,
    "storage": 2.0,
    "gpu": 6.0,
    "smart": 15.0,
    "host": 5.0,
}
DEFAULT_COMMAND_SLOW_SECONDS = 2.0
```

- [ ] **Step 5: Run observability tests GREEN**

```bash
cd dh_pve_app
PYTHONPATH=. python -m pytest tests/test_observability.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add dh_pve_app/app/observability.py dh_pve_app/tests/test_observability.py
git commit -m "feat(dh-pve): add runtime observability accumulator"
```

---

### Task 2: Instrument collector duration and failure/recovery centrally

**Files:**
- Modify: `dh_pve_app/app/app.py` around `DhPveRuntime.__init__()` and `_collect_one()`.
- Modify: `dh_pve_app/tests/test_app_runtime.py`.

**Interfaces:**
- Consumes: `RuntimeObserver.record_collector(name, duration_seconds, success, error_type=None)` from Task 1.
- Produces: all PVE collectors are measured from one central boundary without collector-specific wrappers.

- [ ] **Step 1: Add failing runtime tests**

Extend `make_runtime()` so it can inject an observer and a deterministic monotonic sequence. Add:

```python
def test_collect_one_records_success_duration_without_changing_state(): ...
def test_collect_one_records_failure_and_preserves_previous_data(): ...
def test_collector_recovery_is_recorded_once(): ...
```

Use a clock iterator such as `iter([10.0, 10.25, 20.0, 20.75])` and assert durations `0.25`, `0.75`.

- [ ] **Step 2: Verify RED**

```bash
cd dh_pve_app
PYTHONPATH=. python -m pytest tests/test_app_runtime.py -q
```

Expected: new observer injection/records absent.

- [ ] **Step 3: Add optional observer to `DhPveRuntime`**

Keep backward compatibility for tests/callers:

```python
def __init__(..., observer: RuntimeObserver | None = None, ...) -> None:
    self.observer = observer
```

Wrap the existing collector body using the already-injected `now_monotonic`:

```python
started = self.now_monotonic()
try:
    ... existing collector validation/state update ...
except Exception as exc:
    ... existing unavailable state behavior ...
finally:
    duration = max(0.0, self.now_monotonic() - started)
```

Record success/failure in `finally` without allowing observer exceptions to escape. Do **not** alter `SubsystemState.error`, retained previous data, publication policy, scheduler, or refresh behavior.

- [ ] **Step 4: Run focused runtime tests GREEN**

```bash
cd dh_pve_app
PYTHONPATH=. python -m pytest tests/test_app_runtime.py tests/test_app_adaptive_runtime.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dh_pve_app/app/app.py dh_pve_app/tests/test_app_runtime.py
git commit -m "feat(dh-pve): measure collector execution"
```

---

### Task 3: Add one sanitized instrumented command runner

**Files:**
- Create: `dh_pve_app/app/command_runner.py`
- Create: `dh_pve_app/tests/test_command_runner.py`

**Interfaces:**
- Consumes: `RuntimeObserver.record_command()`.
- Produces: callable `InstrumentedCommandRunner.__call__(argv, *, timeout=20.0, check=True) -> str` matching the current `production._run()` seam.
- Produces: `command_key(argv) -> str` and `sanitize_argv(argv) -> tuple[str, ...]` used only for diagnostics.

- [ ] **Step 1: Write RED tests for subprocess semantics**

Tests must prove that successful stdout, non-zero `CalledProcessError`, and `TimeoutExpired` behavior stay compatible with the existing runner:

```python
def test_runner_returns_stdout_and_records_stable_key(): ...
def test_runner_preserves_check_true_failure(): ...
def test_runner_records_timeout_and_reraises_timeout(): ...
def test_runner_does_not_log_password_or_guest_payload(): ...
```

Map at least these stable families:

```text
pvesh get /cluster/resources -> pvesh.cluster_resources
qm list                       -> qm.list
pct list                      -> pct.list
qm agent <id> ping            -> qm.agent_ping
qm guest exec ... intel_gpu_top -> qm.guest_exec.gpu
pvesm status                  -> pvesm.status
smartctl ...                  -> smartctl.read
lspci ...                     -> lspci.inventory
```

Unknown commands use `command.<basename>`; never include a password or arbitrary argument payload in an INFO/WARNING message.

- [ ] **Step 2: Verify RED**

```bash
cd dh_pve_app
PYTHONPATH=. python -m pytest tests/test_command_runner.py -q
```

- [ ] **Step 3: Implement runner**

Structure:

```python
class InstrumentedCommandRunner:
    def __init__(self, observer: RuntimeObserver, *, runner=subprocess.run, monotonic=time.monotonic): ...

    def __call__(self, argv: list[str], *, timeout: float = 20.0, check: bool = True) -> str:
        started = self.monotonic()
        try:
            completed = self.runner(...)
            return completed.stdout
        except subprocess.TimeoutExpired:
            self.observer.record_command(key, elapsed, success=False, timeout=True)
            raise
        except Exception:
            self.observer.record_command(key, elapsed, success=False)
            raise
        finally:
            # successful path records exactly once
            ...
```

Use a boolean to avoid double-recording in `finally`. The observer itself owns warning thresholds; the runner only supplies stable key, duration/result category and sanitized diagnostic label.

- [ ] **Step 4: Run command-runner tests GREEN**

```bash
cd dh_pve_app
PYTHONPATH=. python -m pytest tests/test_command_runner.py -q
```

- [ ] **Step 5: Commit**

```bash
git add dh_pve_app/app/command_runner.py dh_pve_app/tests/test_command_runner.py
git commit -m "feat(dh-pve): add instrumented command runner"
```

---

### Task 4: Route expensive production paths through the runner

**Files:**
- Modify: `dh_pve_app/app/production.py`
- Modify: `dh_pve_app/app/production_guest.py`
- Modify: `dh_pve_app/app/topology.py`
- Modify: `dh_pve_app/app/shutdown_integration.py` only if constructor forwarding is required.
- Modify tests: `test_topology.py`, `test_gpu.py`, `test_smart.py`, `test_storage.py`, `test_production_v1.py`, relevant guest tests.

**Interfaces:**
- Consumes: `InstrumentedCommandRunner` callable from Task 3.
- Produces: one runner instance is reused by topology and production collectors; no nested duplicate timing for the same subprocess.

- [ ] **Step 1: Write/adjust failing injection tests**

Prove `ProductionCollectors` accepts `runner=` and uses it for CLI calls. Add a fake runner that records argv and returns fixtures.

Example contract:

```python
collector = ProductionCollectors(
    node_name="pve",
    disk_state_store=store,
    runner=fake_runner,
)
collector.storage()
assert ["pvesm", "status"] in fake_runner.commands
```

For `TopologyManager`, retain its existing `runner` API and assert cluster resources and QGA calls go through that same object.

- [ ] **Step 2: Verify RED**

```bash
cd dh_pve_app
PYTHONPATH=. python -m pytest tests/test_topology.py tests/test_gpu.py tests/test_smart.py tests/test_storage.py tests/test_production_v1.py -q
```

- [ ] **Step 3: Inject runner into production collectors**

Change `ProductionCollectors.__init__()` to accept:

```python
runner: Callable[..., str] = _run
```

Store it as `self.runner` and replace direct `_run(...)` calls in production paths with `self.runner(...)`. `GuestAwareProductionCollectors` must forward/reuse it instead of calling `base_production._run` directly.

Do not instrument pure file reads or parser functions.

- [ ] **Step 4: Remove silent command-loss in GPU/SMART paths**

Where an exception is intentionally swallowed because one device/guest is optional, keep that resilience but let the instrumented runner record the failed/slow subprocess before the exception is swallowed. Do not add a second warning in the collector loop for the same command failure.

- [ ] **Step 5: Run focused collector regression suite GREEN**

```bash
cd dh_pve_app
PYTHONPATH=. python -m pytest \
  tests/test_topology.py \
  tests/test_gpu.py \
  tests/test_smart.py \
  tests/test_storage.py \
  tests/test_production_v1.py \
  tests/test_guests.py -q
```

- [ ] **Step 6: Commit**

```bash
git add dh_pve_app/app/production.py dh_pve_app/app/production_guest.py dh_pve_app/app/topology.py dh_pve_app/app/shutdown_integration.py dh_pve_app/tests
git commit -m "refactor(dh-pve): instrument production subprocesses"
```

---

### Task 5: Add host/app/NUT performance sampler

**Files:**
- Create: `dh_pve_app/app/performance.py`
- Create: `dh_pve_app/tests/test_performance.py`

**Interfaces:**
- Produces: `PerformanceSnapshot` and `PerformanceSampler.sample(now_monotonic: float) -> PerformanceSnapshot`.
- Consumes later: `RuntimeObserver.maybe_log_summaries(..., performance=...)`.

- [ ] **Step 1: Write deterministic RED tests**

Use temporary fixture files, never the real CI cgroup tree. Cover:

```python
def test_host_cpu_uses_proc_stat_delta(): ...
def test_service_cpu_is_percent_of_one_core_from_cpu_stat_usage_usec_delta(): ...
def test_missing_nut_cgroup_returns_none_without_raising(): ...
def test_app_rss_reads_memory_current_or_proc_status(): ...
def test_load_average_is_read_without_subprocess(): ...
```

Expected formula for service CPU:

```python
percent_core = (delta_usage_usec / (delta_monotonic_seconds * 1_000_000.0)) * 100.0
```

Do not divide by logical CPU count; `100%core` means one saturated logical core.

- [ ] **Step 2: Verify RED**

```bash
cd dh_pve_app
PYTHONPATH=. python -m pytest tests/test_performance.py -q
```

- [ ] **Step 3: Implement sampler**

`PerformanceSnapshot` fields:

```python
@dataclass(frozen=True)
class PerformanceSnapshot:
    host_cpu_percent: float | None
    load1: float | None
    app_cpu_percent_core: float | None
    nut_cpu_percent_core: float | None
    app_rss_bytes: int | None
```

Read host CPU from `/proc/stat`; read service usage from cgroup-v2 `cpu.stat`. Resolve app cgroup from `/proc/self/cgroup`; resolve `nut-monitor.service` under `/sys/fs/cgroup/system.slice/nut-monitor.service` with graceful fallback to `None`. Do not spawn `systemctl` every minute.

Temperature remains sourced from the already-collected CPU subsystem when main formats PERF; do not duplicate hwmon scanning here.

- [ ] **Step 4: Run performance tests GREEN**

```bash
cd dh_pve_app
PYTHONPATH=. python -m pytest tests/test_performance.py -q
```

- [ ] **Step 5: Commit**

```bash
git add dh_pve_app/app/performance.py dh_pve_app/tests/test_performance.py
git commit -m "feat(dh-pve): sample host and service CPU"
```

---

### Task 6: Wire 60-second summaries into production main loop

**Files:**
- Modify: `dh_pve_app/app/main.py`
- Modify: `dh_pve_app/app/app.py` only for observer exposure if needed.
- Modify: `dh_pve_app/tests/test_main_contract.py`
- Modify: `dh_pve_app/tests/test_observability.py`

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces: production journal lines `PERF`, `COLLECTORS`, `COMMANDS` once per 60-second window.

- [ ] **Step 1: Add RED wiring/cadence tests**

Patch/inject fake observer, runner and performance sampler. Assert `build_runtime()` passes the same observer to `DhPveRuntime` and the same instrumented runner to topology/production.

Assert the loop-facing method behaves like:

```python
observer.maybe_log_summaries(
    now=time.monotonic(),
    performance=performance_sampler.sample(...),
    cpu_temperature_c=current_cpu_temperature,
    ups_state=current_ups_state,
)
```

and emits at most once per 60 seconds.

- [ ] **Step 2: Verify RED**

```bash
cd dh_pve_app
PYTHONPATH=. python -m pytest tests/test_main_contract.py tests/test_observability.py -q
```

- [ ] **Step 3: Build observer/runner once**

In `build_runtime()`/`run()` create one `RuntimeObserver`, one `InstrumentedCommandRunner`, and one `PerformanceSampler`. Pass the same runner to `ShutdownAwareTopologyManager` and `ShutdownAwareProductionCollectors`.

Do not create one runner per collector; aggregation must represent the whole process window.

- [ ] **Step 4: Emit compact summaries**

Target line shapes:

```text
PERF window=60s host_cpu=42.1% temp=84.0C load1=1.89 app_cpu=8.3%core nut_cpu=99.1%core app_rss=214MiB ups=OB
COLLECTORS window=60s cpu=count:6 avg:0.012s max:0.018s fail:0 gpu=count:2 avg:4.800s max:5.000s fail:0
COMMANDS window=60s pvesh.cluster_resources=count:2 total:2.200s max:1.200s fail:0 qm.guest_exec.gpu=count:2 total:9.700s max:5.000s fail:0
```

Missing fields render as `n/a`; failure to sample one metric is not a runtime exception.

- [ ] **Step 5: Run main/runtime regression tests GREEN**

```bash
cd dh_pve_app
PYTHONPATH=. python -m pytest \
  tests/test_main_contract.py \
  tests/test_app_runtime.py \
  tests/test_app_adaptive_runtime.py \
  tests/test_observability.py \
  tests/test_performance.py -q
```

- [ ] **Step 6: Commit**

```bash
git add dh_pve_app/app/main.py dh_pve_app/app/app.py dh_pve_app/tests/test_main_contract.py dh_pve_app/tests/test_observability.py
git commit -m "feat(dh-pve): log minute runtime summaries"
```

---

### Task 7: Bound burst logging at the systemd boundary

**Files:**
- Modify: `dh_pve_app/systemd/dh_pve_app.service`
- Modify: `dh_pve_app/tests/test_main_contract.py` or create `tests/test_systemd_contract.py`.

**Interfaces:**
- Produces: per-unit journal burst protection; no global journald changes.

- [ ] **Step 1: Add RED unit-file contract test**

Read the unit file as text and require exactly:

```ini
LogRateLimitIntervalSec=30s
LogRateLimitBurst=200
```

Also assert no `StandardOutput=file:`/`append:` and no custom logfile path is introduced.

- [ ] **Step 2: Verify RED**

```bash
cd dh_pve_app
PYTHONPATH=. python -m pytest tests/test_main_contract.py -q
```

- [ ] **Step 3: Add service directives under `[Service]`**

```ini
LogRateLimitIntervalSec=30s
LogRateLimitBurst=200
```

Keep existing hardening, `ProtectSystem=full`, restart behavior and stdout/stderr defaults unchanged.

- [ ] **Step 4: Verify unit syntax**

```bash
sudo install -d /opt/digitalhouses/dh_pve_app/.venv/bin
sudo ln -sf "$(command -v python3)" /opt/digitalhouses/dh_pve_app/.venv/bin/python
systemd-analyze verify dh_pve_app/systemd/*.service
```

Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add dh_pve_app/systemd/dh_pve_app.service dh_pve_app/tests/test_main_contract.py
git commit -m "chore(dh-pve): bound journal burst logging"
```

---

### Task 8: Extend the canonical shutdown incident timeline

**Files:**
- Modify: `dh_pve_app/app/shutdown_history.py`
- Modify: `dh_pve_app/app/shutdown_integration.py`
- Modify: `dh_pve_app/tests/test_shutdown_history.py`
- Modify: `dh_pve_app/tests/test_shutdown_reason_separation.py`

**Interfaces:**
- Produces: persisted `current_boot.policy_snapshot`, expanded `previous_shutdown` incident timeline.
- Adds tracker method: `set_policy_snapshot(snapshot: Mapping[str, object]) -> None`.
- Existing `observe_ups()` remains the source for outage/FSD telemetry.

- [ ] **Step 1: Write RED parsing/timeline tests using the real incident shape**

Use a synthetic previous-boot journal containing these ordered events:

```text
2026-09-15T07:27:50+05:00 nut-monitor: UPS ups@127.0.0.1 battery is low
2026-09-15T07:27:57+05:00 nut-monitor: Executing automatic power-fail shutdown
2026-09-15T07:28:10+05:00 pve-guests: Stopping VM 700 (timeout = 180 seconds)
2026-09-15T07:30:00+05:00 pve-guests: all VMs and CTs stopped
2026-09-15T07:31:56+05:00 systemd: Reached target System Power Off
```

Require parser/tracker fields:

```python
assert previous["host_shutdown_started_at"] == "2026-09-15T07:27:57+05:00"
assert previous["all_guests_stopped_at"] == "2026-09-15T07:30:00+05:00"
assert previous["last_shutdown_event_at"] == "2026-09-15T07:31:56+05:00"
assert previous["next_boot_at"] == "2026-09-15T07:34:25+05:00"
assert previous["host_offline_gap_seconds"] == 149
```

- [ ] **Step 2: Add RED policy snapshot immutability test**

During boot A call:

```python
tracker.set_policy_snapshot({
    "policy_revision": 7,
    "guest_shutdown_budget_seconds": 280,
    "power_restore_delay_seconds": 120,
})
```

After transition to boot B, change current policy to revision 8 and assert historical boot A still contains revision 7 unchanged.

- [ ] **Step 3: Implement journal milestone parsing**

Add earliest host-shutdown-start detection for explicit markers, including the observed NUT line:

```python
_HOST_SHUTDOWN_START_MARKERS = (
    "executing automatic power-fail shutdown",
    "auto logout and shutdown proceeding",
    "system is powering down",
)
```

Return both `host_shutdown_started_at` and `last_shutdown_event_at` from `parse_guest_shutdown_journal()` while preserving existing fields for compatibility.

- [ ] **Step 4: Extend startup rollover record**

On boot change set:

```python
"next_boot_at": boot_at,
"host_shutdown_started_at": parsed.get("host_shutdown_started_at"),
"last_shutdown_event_at": parsed.get("last_shutdown_event_at"),
"policy_snapshot": dict(current.get("policy_snapshot") or {}),
```

Derive:

```text
fsd_to_shutdown_start_seconds
shutdown_start_to_guests_stopped_seconds
fsd_to_last_shutdown_event_seconds
host_offline_gap_seconds
fsd_to_next_boot_seconds
```

Do not delete existing duration fields yet; compatibility removal belongs to a later cleanup release.

- [ ] **Step 5: Implement `set_policy_snapshot()`**

Persist only JSON-safe scalar/dict values needed by the incident. If the incoming snapshot equals the stored snapshot, perform no write. Never retroactively edit `history`/`previous_shutdown`.

For the observability release, `ShutdownAwareUpsRuntime` should call it with currently-known legacy/effective fields, for example:

```python
{
    "policy_revision": self.policy_revision,
    "guest_shutdown_budget_seconds": budget,
    "power_restore_delay_seconds": observed_restore_delay,
    "on_battery_delay_minutes": observed_legacy_delay,
}
```

UPS Trigger Policy v2 will later add `battery_charge_low_percent`, `total_shutdown_budget_seconds`, `runtime_safety_reserve_seconds`, and `effective_runtime_trigger_seconds` to the same map.

- [ ] **Step 6: Run shutdown tests GREEN**

```bash
cd dh_pve_app
PYTHONPATH=. python -m pytest \
  tests/test_shutdown_history.py \
  tests/test_shutdown_reason_separation.py \
  tests/test_shutdown_integration.py -q
```

- [ ] **Step 7: Commit**

```bash
git add dh_pve_app/app/shutdown_history.py dh_pve_app/app/shutdown_integration.py dh_pve_app/tests/test_shutdown_history.py dh_pve_app/tests/test_shutdown_reason_separation.py
git commit -m "feat(dh-pve): persist shutdown incident timeline"
```

---

### Task 9: Publish only stable incident history fields, not performance summaries

**Files:**
- Modify: `dh_pve_app/app/shutdown_discovery.py`
- Modify: `dh_pve_app/tests/test_shutdown_group_contract.py`
- Modify: `dh_pve_app/tests/test_shutdown_card_contract.py` if the card renders previous shutdown detail.

**Interfaces:**
- Consumes: expanded `ShutdownHistoryTracker.payload()` from Task 8.
- Produces: HA can inspect last incident timing through existing shutdown-history entities/attributes; no 60-second PERF entities.

- [ ] **Step 1: Add RED discovery contract**

Require previous-shutdown attributes to include the stable new keys:

```text
host_shutdown_started_at
last_shutdown_event_at
next_boot_at
host_offline_gap_seconds
fsd_to_shutdown_start_seconds
fsd_to_last_shutdown_event_seconds
fsd_to_next_boot_seconds
policy_snapshot
```

Also add a negative assertion that Discovery contains no `perf`, `collectors_summary`, or `commands_summary` MQTT entity.

- [ ] **Step 2: Verify RED**

```bash
cd dh_pve_app
PYTHONPATH=. python -m pytest tests/test_shutdown_group_contract.py tests/test_shutdown_card_contract.py -q
```

- [ ] **Step 3: Extend existing shutdown attributes/templates**

Add the fields to the current shutdown-history JSON attributes. Do not create fast-changing dedicated sensors for each duration unless an existing contract already uses one. Publication remains change-only because history changes only on shutdown/boot events.

- [ ] **Step 4: Run contract tests GREEN**

```bash
cd dh_pve_app
PYTHONPATH=. python -m pytest tests/test_shutdown_group_contract.py tests/test_shutdown_card_contract.py -q
```

- [ ] **Step 5: Commit**

```bash
git add dh_pve_app/app/shutdown_discovery.py dh_pve_app/tests/test_shutdown_group_contract.py dh_pve_app/tests/test_shutdown_card_contract.py
git commit -m "feat(dh-pve): expose shutdown incident evidence"
```

---

### Task 10: Documentation, full verification, and non-destructive home-PVE validation

**Files:**
- Modify: `dh_pve_app/README.md`
- Modify: `dh_pve_app/CHANGELOG.md`
- No production behavior changes in this task.

**Interfaces:**
- Produces: release-ready observability branch suitable for deployment before UPS Trigger Policy v2.

- [ ] **Step 1: Update README**

Document exactly:

```text
INFO: startup/stop, transitions, PERF/COLLECTORS/COMMANDS once per 60s
WARNING/ERROR: failed/slow/timeout operations with suppression
DEBUG: per-operation details, disabled by default
Storage: journald only; no app-owned log files
Shutdown history: persisted incident timeline + policy snapshot
```

Include grep examples:

```bash
journalctl -u dh_pve_app.service --since -30min --no-pager | grep -E 'PERF|COLLECTORS|COMMANDS|UPS_TRIGGER|WARNING|ERROR'
```

- [ ] **Step 2: Update CHANGELOG**

Record observability as a separate release/feature section; explicitly state no MQTT publication-rate change and no UPS trigger policy change yet.

- [ ] **Step 3: Run compile + full test suite**

```bash
python -m compileall -q dh_pve_app/app dh_pve_app/tests
PYTHONPATH=dh_pve_app python -m pytest dh_pve_app/tests -q
bash -n dh_pve_app/install.sh
```

Expected: all tests PASS.

- [ ] **Step 4: Verify systemd unit**

```bash
sudo install -d /opt/digitalhouses/dh_pve_app/.venv/bin
sudo ln -sf "$(command -v python)" /opt/digitalhouses/dh_pve_app/.venv/bin/python
systemd-analyze verify dh_pve_app/systemd/*.service
```

Expected: exit 0.

- [ ] **Step 5: Run repository-level validation**

```bash
python scripts/validate_repository.py
```

Expected: PASS.

- [ ] **Step 6: Review final diff before deploy**

```bash
git diff --check
git status --short
git log --oneline --decorate -10
```

Review specifically that no new log file path, cron cleanup, MQTT PERF entity, `upssched` behavior change, or FSD command slipped into this PR.

- [ ] **Step 7: Commit docs**

```bash
git add dh_pve_app/README.md dh_pve_app/CHANGELOG.md
git commit -m "docs(dh-pve): document runtime observability"
```

- [ ] **Step 8: Deploy exact SHA to home PVE non-destructively**

After normal project deploy procedure, capture:

```bash
systemctl status dh_pve_app.service --no-pager
journalctl -u dh_pve_app.service --since -3min --no-pager | grep -E 'PERF|COLLECTORS|COMMANDS|WARNING|ERROR'
```

Wait at least two summary windows. Verify:

```text
- PERF appears once per ~60s
- COLLECTORS appears once per ~60s
- COMMANDS appears once per ~60s when commands ran
- pvesh.cluster_resources timing is visible
- qm.guest_exec.gpu timing is visible when GPU collection runs
- app_cpu and nut_cpu are plausible and independently reported
- Manual Refresh does not create an INFO storm
- MQTT/HA entities and Recorder cadence are unchanged
```

Do **not** unplug mains, trigger FSD, stop UPS output, or run a destructive shutdown as part of this PR.

---

## Self-Review Checklist

Before calling this plan complete, verify all spec requirements map to tasks:

- Collector timing/failure/recovery: Tasks 1–2.
- External command timing and sanitization: Tasks 3–4.
- Host/app/NUT CPU and RSS: Task 5.
- 60-second PERF/COLLECTORS/COMMANDS: Task 6.
- journald-only + 200/30s burst protection: Task 7.
- Durable shutdown timeline + immutable policy snapshot: Task 8.
- HA gets stable incident evidence but no minute telemetry: Task 9.
- Full CI/systemd validation and safe home deployment: Task 10.
- NFS/CIFS/SMB provider dependency detection remains technical debt and is not implemented here.
