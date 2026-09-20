# DH PVE Simplified Runtime Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace regular heavy PVE polling with PVE 8.x local/cache readers, enforce fixed collection cadence, and replace the old adaptive publication engine with rolling decision averages plus per-domain NORMAL/DETAIL MQTT publication.

**Architecture:** This is Plan 1 of 3 for the frozen canonical design. Pure PVE 8.x parsers are introduced first, then production collectors are rewired to consume them without CLI fallback loops, then the scheduler and publication engine are replaced. Discovery/problem/event migration and UPS Trigger Policy v2 are intentionally deferred to Plans 2 and 3 so this phase remains independently testable.

**Tech Stack:** Python 3.13 CI, pytest, Proxmox VE 8.x, pmxcfs `/etc/pve`, `/proc`, `/sys`, existing MQTT bridge/state-store architecture.

**Spec:** `docs/superpowers/specs/2026-09-15-dh-pve-simplified-runtime-haos-design.md`

**Source audit:** `docs/superpowers/specs/2026-09-15-dh-pve-source-audit.md`

## Global Constraints

- Target Proxmox VE 8.x only.
- Source priority is `/proc,/sys` -> `/etc/pve` file/cache -> subprocess only when necessary -> `pvesh`/API rare/on-demand/actions.
- Never implement permanent `file/cache failed -> pvesh/qm/pct/pvesm every poll` fallback.
- Collection cadence is fixed: FAST 10s, UPS 10s, SLOW 60s, HEALTH 3600s, STATIC startup/change/manual refresh.
- `/etc/pve/.version` is checked every SLOW cycle; inotify/local events are optimization only.
- NORMAL publication is 15 minutes; DETAIL publication is 5 minutes; DETAIL never changes acquisition cadence.
- FAST decision windows are 60 seconds; SLOW decision windows are 5 minutes.
- Missing/invalid values are excluded and never converted to zero.
- Decision comparisons are strict: `avg > threshold` enters DETAIL, `avg < threshold` returns NORMAL, equality keeps current state.
- Production code changes use TDD: test first, observe RED, minimal GREEN, refactor only after GREEN.
- No FSD, UPS output-off, mains unplug, deep discharge, HA-side host shutdown, or arbitrary shell/upscmd validation.

---

## File Structure

### New production files

- `dh_pve_app/app/pve_cache.py` — pure readers/parsers for `.version`, `.vmlist`, `.rrd`, `storage.cfg` and PVE 8 freshness rules.
- `dh_pve_app/app/runtime_windows.py` — valid-sample rolling windows and strict profile state transition primitive.
- `dh_pve_app/app/disk_temperature.py` — SLOW disk-temperature reader isolated from full SMART health.

### Existing production files modified

- `dh_pve_app/app/main.py` — fixed task cadence and no MQTT poll controls.
- `dh_pve_app/app/production.py` — split STATIC/SLOW/HEALTH responsibilities and consume cache readers.
- `dh_pve_app/app/production_v1.py` — retain HEALTH SMART fault isolation; remove full-SMART responsibility for SLOW temperature.
- `dh_pve_app/app/production_guest.py` — use cached topology/runtime state; do not run lspci or guest-list commands on SLOW status path.
- `dh_pve_app/app/topology.py` — local pmxcfs inventory/config, no normal `pvesh/qm/pct` fallback loop.
- `dh_pve_app/app/app.py` — explicit STATIC refresh on `.version` change and fixed cadence integration.
- `dh_pve_app/app/presentation.py` — reduce publication profile model to NORMAL/DETAIL.
- `dh_pve_app/app/presentation_policy.py` — strict averaged profile decisions with internal thresholds.
- `dh_pve_app/app/presentation_pve_base.py` — consume averaged values, NORMAL/DETAIL only.
- `dh_pve_app/app/runtime_settings.py` — remove legacy poll interval controls from product contract while tolerating persisted legacy keys during upgrade.
- `dh_pve_app/app/config.py` — UPS polling changes belong to Plan 3; do not mix them into this PVE foundation task.

### New tests/fixtures

- `dh_pve_app/tests/test_pve_cache.py`
- `dh_pve_app/tests/test_disk_temperature.py`
- `dh_pve_app/tests/test_runtime_windows.py`
- `dh_pve_app/tests/fixtures/pve8_version.json`
- `dh_pve_app/tests/fixtures/pve8_vmlist.json`
- `dh_pve_app/tests/fixtures/pve8_rrd.txt`
- `dh_pve_app/tests/fixtures/pve8_storage.cfg`

### Existing tests modified

- `dh_pve_app/tests/test_topology.py`
- `dh_pve_app/tests/test_production_v1.py`
- `dh_pve_app/tests/test_app_runtime.py`
- `dh_pve_app/tests/test_app_adaptive_runtime.py`
- `dh_pve_app/tests/test_main_contract.py`
- `dh_pve_app/tests/test_presentation.py`
- `dh_pve_app/tests/test_presentation_pve.py`
- related contract tests only where the old QUIET/HIGH/CRITICAL or poll controls are explicitly asserted.

---

### Task 1: Add PVE 8 pmxcfs/cache parsers

**Files:**
- Create: `dh_pve_app/app/pve_cache.py`
- Create: `dh_pve_app/tests/test_pve_cache.py`
- Create fixtures: `dh_pve_app/tests/fixtures/pve8_version.json`, `pve8_vmlist.json`, `pve8_rrd.txt`, `pve8_storage.cfg`

**Interfaces:**
- Produces `PveVersionSnapshot`, `PveGuestInventory`, `PveRrdSnapshot`, `PveStorageConfig` dataclasses.
- Produces `read_pve_version(path)`, `read_pve_vmlist(path)`, `read_pve_rrd(path, *, now_epoch, stale_after_seconds=120)`, `read_storage_config(path)`.
- Later tasks consume these readers; none may spawn subprocesses.

- [ ] **Step 1: Write failing `.version` and `.vmlist` parser tests.**

```python
from pathlib import Path
from app.pve_cache import read_pve_version, read_pve_vmlist

FIXTURES = Path(__file__).parent / "fixtures"


def test_pve_version_returns_stable_fingerprint_for_parsed_json():
    snap = read_pve_version(FIXTURES / "pve8_version.json")
    assert snap.vmlist_version == 42
    assert snap.fingerprint


def test_pve_vmlist_maps_local_qemu_and_lxc_without_runtime_status():
    snap = read_pve_vmlist(FIXTURES / "pve8_vmlist.json")
    assert snap.guests["110"].kind == "vm"
    assert snap.guests["700"].kind == "vm"
    assert snap.guests["1011"].kind == "lxc"
    assert snap.guests["110"].node == "pve"
```

Fixture content must represent the upstream PVE 8 shape:

```json
{"starttime": 1720000000, "clinfo": 1, "vmlist": 42, "storage.cfg": 7, "kvstore": {}}
```

```json
{"version": 42, "ids": {"110": {"node": "pve", "type": "qemu", "version": 11}, "700": {"node": "pve", "type": "qemu", "version": 12}, "1011": {"node": "pve", "type": "lxc", "version": 13}}}
```

- [ ] **Step 2: Run focused tests and verify RED.**

Run:

```bash
cd dh_pve_app
PYTHONPATH=. python -m pytest tests/test_pve_cache.py -q
```

Expected: import failure because `app.pve_cache` does not exist.

- [ ] **Step 3: Implement minimal `.version`/`.vmlist` readers.**

Use immutable dataclasses and canonical JSON hashing:

```python
@dataclass(frozen=True)
class PveGuestInventoryItem:
    vmid: str
    kind: str
    node: str
    version: int | None

@dataclass(frozen=True)
class PveVersionSnapshot:
    raw: Mapping[str, object]
    vmlist_version: int | None
    fingerprint: str
```

Reject a non-object JSON root. Ignore unsupported guest types instead of treating them as qemu/lxc.

- [ ] **Step 4: Add failing PVE 8 `.rrd` tests.**

Fixture lines:

```text
pve2-node/pve:3600::1720000100:0.42:4:0.15:0.01:16000000000:4000000000:2000000000:100000000:32000000000:12000000000:1000:2000
pve2.3-vm/110:900:haos:running:0:1720000100:4:0.02:4294967296:2147483648:34359738368:8589934592:100:200:300:400
pve2.3-vm/700:0:truenas:stopped:0:1720000100:4:U:4294967296:U:34359738368:8589934592:U:U:U:U
pve2-storage/pve/local-lvm:1720000100:1000000000:700000000
```

Tests:

```python
def test_pve_rrd_parses_guest_status_and_storage_usage_without_zeroing_unknowns():
    snap = read_pve_rrd(FIXTURES / "pve8_rrd.txt", now_epoch=1720000110)
    assert snap.guests["110"].status == "running"
    assert snap.guests["700"].cpu is None
    assert snap.storages["local-lvm"].used == 700000000
    assert snap.storages["local-lvm"].usage_percent == 70.0


def test_pve_rrd_rejects_stale_records():
    snap = read_pve_rrd(FIXTURES / "pve8_rrd.txt", now_epoch=1720000300)
    assert snap.guests == {}
    assert snap.storages == {}
```

- [ ] **Step 5: Implement PVE 8 RRD parser.**

Rules:

```python
if token == "U":
    value = None
```

Validate minimum field counts, use `ctime` for freshness, ignore unknown keys and future trailing fields. Do not infer VM/LXC kind from the RRD key.

- [ ] **Step 6: Add storage.cfg parser RED/GREEN.**

Fixture:

```text
dir: local
    path /var/lib/vz
    content iso,vztmpl,backup

nfs: truenas_data
    server 192.168.11.31
    export /mnt/sky_pool/data
    content images,iso,vztmpl,backup,snippets
```

Required assertion:

```python
cfg = read_storage_config(FIXTURES / "pve8_storage.cfg")
assert cfg["truenas_data"].storage_type == "nfs"
assert cfg["truenas_data"].options["server"] == "192.168.11.31"
```

- [ ] **Step 7: Run tests GREEN and commit.**

```bash
cd dh_pve_app
PYTHONPATH=. python -m pytest tests/test_pve_cache.py -q
git add app/pve_cache.py tests/test_pve_cache.py tests/fixtures/pve8_*.json tests/fixtures/pve8_rrd.txt tests/fixtures/pve8_storage.cfg
git commit -m "feat(dh-pve): add PVE 8 cache readers"
```

---

### Task 2: Rewire guest/storage runtime to cheap cache sources

**Files:**
- Modify: `dh_pve_app/app/topology.py`
- Modify: `dh_pve_app/app/production_guest.py`
- Modify: `dh_pve_app/app/production.py`
- Modify: `dh_pve_app/tests/test_topology.py`
- Modify: `dh_pve_app/tests/test_production_v1.py`

**Interfaces:**
- Consumes Task 1 `PveVmListReader`/`PveRrdReader` behavior.
- Produces guest runtime status from `.rrd`, storage usage from `.rrd`, static config from pmxcfs files.
- No regular `pvesh`, `qm list`, `pct list`, `pvesm status`, `qm config`, or `pct config` path remains.

- [ ] **Step 1: Write failing topology tests proving no command fallback is used.**

Use temporary pmxcfs fixtures and a runner that fails if called:

```python
def forbidden_runner(*args, **kwargs):
    raise AssertionError(f"unexpected subprocess: {args!r}")


def test_guest_status_uses_vmlist_and_rrd_without_pvesh_qm_pct(tmp_path):
    manager = TopologyManager(
        runner=forbidden_runner,
        pve_root=tmp_path,
        node_name="pve",
        now_epoch=lambda: 1720000110,
    )
    snapshot = manager.poll_guest_status()
    assert snapshot.vms["110"].status == "running"
```

Build the temporary tree with `.vmlist`, `.rrd`, `qemu-server/*.conf`, and `lxc/*.conf`.

- [ ] **Step 2: Run topology test and verify RED because current code invokes `pvesh`.**

```bash
cd dh_pve_app
PYTHONPATH=. python -m pytest tests/test_topology.py -q
```

- [ ] **Step 3: Replace `_guest_lists()` normal path with local cache readers.**

Use `.vmlist` for type/node/name fallback and `.rrd` for current status. `_read_config()` returns direct file contents or raises/returns explicit unavailable state; it must not execute `qm config`/`pct config`.

- [ ] **Step 4: Write failing storage collector test.**

```python
def test_storage_reads_pve_rrd_without_pvesm(tmp_path):
    collectors = ProductionCollectors(
        node_name="pve",
        disk_state_store=FakeStore(),
        pve_root=tmp_path,
    )
    sample = collectors.storage()
    assert sample.data["local-lvm"]["usage_percent"] == 70.0
```

Monkeypatch the legacy `_run` to fail if invoked.

- [ ] **Step 5: Implement storage from `.rrd` + `storage.cfg`.**

Expose configured storage inventory even when current runtime data is absent; missing fresh RRD data becomes unavailable/inactive, never zero-used.

- [ ] **Step 6: Remove normal CLI fallback assertions and run focused suite GREEN.**

```bash
cd dh_pve_app
PYTHONPATH=. python -m pytest tests/test_topology.py tests/test_production_v1.py -q
```

- [ ] **Step 7: Commit.**

```bash
git add app/topology.py app/production.py app/production_guest.py tests/test_topology.py tests/test_production_v1.py
git commit -m "refactor(dh-pve): use PVE cache for guest and storage runtime"
```

---

### Task 3: Split SLOW disk temperature from HEALTH SMART

**Files:**
- Create: `dh_pve_app/app/disk_temperature.py`
- Create: `dh_pve_app/tests/test_disk_temperature.py`
- Modify: `dh_pve_app/app/production.py`
- Modify: `dh_pve_app/app/production_v1.py`

**Interfaces:**
- Produces `DiskTemperatureReader.read(disk) -> DiskTemperatureSample`.
- Sysfs/hwmon is first choice; explicitly bounded SMART temperature fallback is second choice.
- Full `smartctl -a -j` stays HEALTH only.

- [ ] **Step 1: Write RED test for sysfs-first temperature.**

```python
def test_disk_temperature_uses_hwmon_without_smartctl(tmp_path):
    called = False
    def runner(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("smartctl must not run when hwmon is available")
    sample = DiskTemperatureReader(sys_root=tmp_path, runner=runner).read(disk_fixture)
    assert sample.temperature_c == 41.0
    assert sample.source == "sysfs"
    assert called is False
```

- [ ] **Step 2: Verify RED, then implement sysfs mapping minimally.**

Map known block/NVMe device identity to attached hwmon. Invalid sensor content returns no value rather than zero.

- [ ] **Step 3: Write RED test for bounded SMART fallback.**

```python
def test_disk_temperature_falls_back_to_temperature_smart_read_without_full_health():
    sample = reader.read(disk_without_hwmon)
    assert sample.temperature_c == 37.0
    assert sample.source == "smartctl"
    assert recorded_argv[0] == "smartctl"
    assert "-a" not in recorded_argv
```

Use a command form that requests only the required SMART attributes/JSON and standby-safe behavior where supported by the tested device type.

- [ ] **Step 4: Split collector responsibilities.**

Target mapping:

```text
disk_temperature -> SLOW
disk_health      -> HEALTH
```

`production_v1.smart()` retains health/wear/counters and per-disk fault isolation but no longer supplies the SLOW temperature cadence.

- [ ] **Step 5: Run disk/SMART tests GREEN and commit.**

```bash
cd dh_pve_app
PYTHONPATH=. python -m pytest tests/test_disk_temperature.py tests/test_smart.py tests/test_production_v1.py -q
git add app/disk_temperature.py app/production.py app/production_v1.py tests/test_disk_temperature.py tests/test_production_v1.py
git commit -m "refactor(dh-pve): split disk temperature from SMART health"
```

---

### Task 4: Enforce fixed collection scheduler and STATIC change refresh

**Files:**
- Modify: `dh_pve_app/app/main.py`
- Modify: `dh_pve_app/app/app.py`
- Modify: `dh_pve_app/app/runtime_settings.py`
- Modify: `dh_pve_app/tests/test_main_contract.py`
- Modify: `dh_pve_app/tests/test_app_runtime.py`
- Modify: `dh_pve_app/tests/test_config.py` only for legacy-setting compatibility assertions if required.

**Interfaces:**
- Produces fixed internal cadence constants:

```python
FAST_SECONDS = 10.0
SLOW_SECONDS = 60.0
HEALTH_SECONDS = 3600.0
```

- STATIC is event-driven and not a repeating scheduler interval.
- `.version` check is part of SLOW and queues/executes STATIC refresh on change.

- [ ] **Step 1: Write failing main contract tests.**

Assert exact production intervals and absence of setting-task mappings for poll controls:

```python
def test_runtime_scheduler_uses_frozen_collection_cadence():
    bridge, runtime = build_runtime(config, ...)
    assert runtime.scheduler.interval("cpu") == 10.0
    assert runtime.scheduler.interval("memory") == 10.0
    assert runtime.scheduler.interval("fans") == 10.0
    assert runtime.scheduler.interval("guests") == 60.0
    assert runtime.scheduler.interval("storage") == 60.0
    assert runtime.scheduler.interval("gpu") == 60.0
    assert runtime.scheduler.interval("smart") == 3600.0
    assert "fast_poll_interval_seconds" not in runtime.setting_tasks
    assert "disk_poll_interval_seconds" not in runtime.setting_tasks
```

If `Scheduler.interval()` does not exist, add the minimal read-only inspection method under test rather than testing private dictionary layout.

- [ ] **Step 2: Verify RED.**

```bash
cd dh_pve_app
PYTHONPATH=. python -m pytest tests/test_main_contract.py -q
```

- [ ] **Step 3: Implement fixed scheduler wiring.**

Do not expose cadence through MQTT settings. Preserve reading/ignoring old persisted keys during upgrade only if needed to avoid startup failure; they must not change cadence.

- [ ] **Step 4: Write `.version` refresh RED test.**

Test sequence:

```text
SLOW sees fingerprint A -> no STATIC refresh
next SLOW sees fingerprint B -> exactly one STATIC refresh
next SLOW still B -> no duplicate STATIC refresh
Manual Refresh -> STATIC + FAST + SLOW + HEALTH
```

- [ ] **Step 5: Implement change-triggered STATIC refresh with no inotify dependency.**

Keep local event support optional; correctness comes from SLOW `.version` comparison.

- [ ] **Step 6: Run focused runtime tests GREEN and commit.**

```bash
cd dh_pve_app
PYTHONPATH=. python -m pytest tests/test_main_contract.py tests/test_app_runtime.py tests/test_config.py -q
git add app/main.py app/app.py app/runtime_settings.py app/scheduler.py tests/test_main_contract.py tests/test_app_runtime.py tests/test_config.py
git commit -m "refactor(dh-pve): enforce fixed collection cadence"
```

---

### Task 5: Add valid-sample rolling decision windows

**Files:**
- Create: `dh_pve_app/app/runtime_windows.py`
- Create: `dh_pve_app/tests/test_runtime_windows.py`

**Interfaces:**
- Produces `RollingAverage(window_seconds)` with `observe(now, value)` and `average(now)`.
- Produces `TwoProfileDecision(threshold, initial=PublicationProfile.NORMAL)` with strict transition semantics.

- [ ] **Step 1: Write failing rolling-window tests.**

```python
def test_rolling_average_excludes_missing_and_expired_samples():
    window = RollingAverage(60.0)
    window.observe(0.0, 10.0)
    window.observe(10.0, None)
    window.observe(20.0, 30.0)
    assert window.average(20.0) == 20.0
    assert window.average(70.1) == 30.0


def test_empty_window_returns_none_not_zero():
    assert RollingAverage(60.0).average(100.0) is None
```

- [ ] **Step 2: Verify RED, then implement minimal window.**

Reject booleans/non-finite numeric values as invalid samples.

- [ ] **Step 3: Write strict threshold RED tests.**

```python
def test_profile_uses_strict_comparison_and_keeps_state_on_equality():
    decision = TwoProfileDecision(threshold=80.0)
    assert decision.update(81.0) is PublicationProfile.DETAIL
    assert decision.update(80.0) is PublicationProfile.DETAIL
    assert decision.update(79.0) is PublicationProfile.NORMAL
    assert decision.update(None) is PublicationProfile.NORMAL
```

- [ ] **Step 4: Implement minimal decision state and run GREEN.**

```bash
cd dh_pve_app
PYTHONPATH=. python -m pytest tests/test_runtime_windows.py -q
git add app/runtime_windows.py tests/test_runtime_windows.py
git commit -m "feat(dh-pve): add rolling decision windows"
```

---

### Task 6: Replace QUIET/HIGH/CRITICAL publication with NORMAL/DETAIL

**Files:**
- Modify: `dh_pve_app/app/presentation.py`
- Modify: `dh_pve_app/app/presentation_policy.py`
- Modify: `dh_pve_app/app/presentation_pve_base.py`
- Modify: `dh_pve_app/tests/test_presentation.py`
- Modify: `dh_pve_app/tests/test_presentation_pve.py`
- Modify: `dh_pve_app/tests/test_app_adaptive_runtime.py`

**Interfaces:**
- `PublicationProfile` has only `NORMAL` and `DETAIL` for runtime publication.
- `ProfileWindows` defaults to NORMAL=900s and DETAIL=300s.
- CPU/memory/disk/GPU selectors consume decision averages rather than latest-sample deltas.
- A profile change never schedules/collects anything.

- [ ] **Step 1: Write RED tests for profile enum/windows.**

```python
def test_publication_profiles_are_only_normal_and_detail():
    assert {item.value for item in PublicationProfile} == {"normal", "detail"}


def test_publication_windows_match_frozen_contract():
    windows = ProfileWindows()
    assert windows.normal_seconds == 900.0
    assert windows.detail_seconds == 300.0
```

- [ ] **Step 2: Verify RED against current QUIET/NORMAL/HIGH/CRITICAL implementation.**

```bash
cd dh_pve_app
PYTHONPATH=. python -m pytest tests/test_presentation.py tests/test_presentation_pve.py -q
```

- [ ] **Step 3: Implement two-profile publication core using Task 5 windows.**

Continuous published telemetry is an average over the active publication period. Discrete semantic transitions remain immediate and do not wait for 5/15 minutes.

- [ ] **Step 4: Add domain-isolation test.**

```python
def test_cpu_detail_does_not_change_gpu_or_storage_profile():
    router = PvePresentationRouter()
    # feed CPU samples above its internal decision threshold
    ...
    profiles = router.profile_summary()
    assert profiles["cpu"] == "DETAIL"
    assert profiles["gpu"] == "NORMAL"
    assert profiles["storage"] == "NORMAL"
```

Use real router inputs/helpers already present in the test suite; do not assert implementation-private containers.

- [ ] **Step 5: Add test proving publication decisions never mutate scheduler cadence.**

The runtime scheduler object must have identical intervals before and after a CPU DETAIL transition.

- [ ] **Step 6: Run focused publication/runtime suite GREEN and commit.**

```bash
cd dh_pve_app
PYTHONPATH=. python -m pytest tests/test_presentation.py tests/test_presentation_pve.py tests/test_app_adaptive_runtime.py tests/test_runtime_windows.py -q
git add app/presentation.py app/presentation_policy.py app/presentation_pve_base.py tests/test_presentation.py tests/test_presentation_pve.py tests/test_app_adaptive_runtime.py
git commit -m "refactor(dh-pve): use NORMAL DETAIL publication profiles"
```

---

### Task 7: Remove repeated GPU/topology inventory work from SLOW telemetry

**Files:**
- Modify: `dh_pve_app/app/topology.py`
- Modify: `dh_pve_app/app/production_guest.py`
- Modify: `dh_pve_app/tests/test_topology.py`
- Modify: `dh_pve_app/tests/test_gpu.py`

**Interfaces:**
- STATIC topology cache owns lspci/config ownership.
- SLOW GPU telemetry consumes cached inventory + SLOW guest status and may run only necessary `intel_gpu_top`/QGA GPU utilization work.

- [ ] **Step 1: Write RED test asserting SLOW GPU collection does not invoke `lspci`, `pvesh`, `qm list`, `pct list`, or QGA ping.**

Record runner argv and permit only the explicitly expected `intel_gpu_top` or `qm guest exec ... intel_gpu_top` call for the chosen fixture.

- [ ] **Step 2: Verify RED against current `GuestAwareProductionCollectors.gpu()`.**

- [ ] **Step 3: Cache STATIC GPU catalog/ownership in `TopologyManager` and consume it from GPU SLOW collector.**

If the owner is a VM, use RRD guest state to decide whether a QGA GPU telemetry attempt is meaningful. Do not execute a separate ping first.

- [ ] **Step 4: Run GPU/topology tests GREEN and commit.**

```bash
cd dh_pve_app
PYTHONPATH=. python -m pytest tests/test_gpu.py tests/test_topology.py -q
git add app/topology.py app/production_guest.py tests/test_gpu.py tests/test_topology.py
git commit -m "refactor(dh-pve): cache static GPU topology"
```

---

### Task 8: Foundation integration, regression suite and source-contract review

**Files:**
- Modify only files required by failing integration tests; no Discovery/UPS-policy feature creep.

**Interfaces:**
- Delivers Plan 1 runtime foundation ready for Plan 2.

- [ ] **Step 1: Run focused collector/runtime suites.**

```bash
cd dh_pve_app
PYTHONPATH=. python -m pytest \
  tests/test_pve_cache.py \
  tests/test_cpu.py \
  tests/test_memory.py \
  tests/test_cooling.py \
  tests/test_storage.py \
  tests/test_smart.py \
  tests/test_disk_temperature.py \
  tests/test_gpu.py \
  tests/test_topology.py \
  tests/test_production_v1.py \
  tests/test_runtime_windows.py \
  tests/test_app_runtime.py \
  tests/test_app_adaptive_runtime.py \
  tests/test_presentation.py \
  tests/test_presentation_pve.py \
  tests/test_main_contract.py -q
```

- [ ] **Step 2: Run full Python test suite.**

```bash
cd dh_pve_app
PYTHONPATH=. python -m pytest -q
```

- [ ] **Step 3: Search production code for forbidden regular polling paths.**

```bash
grep -RInE 'pvesh|pvesm["'"' ]+status|qm["'"' ]+list|pct["'"' ]+list' dh_pve_app/app
```

Every remaining match must be classified as migration-only, explicit action/on-demand, test compatibility, or removed. There must be no SLOW/FAST regular polling path using those commands.

- [ ] **Step 4: Search for obsolete publication profiles and poll controls.**

```bash
grep -RInE 'QUIET|HIGH|CRITICAL|fast_poll_interval_seconds|disk_poll_interval_seconds' dh_pve_app/app
```

Production runtime must not use these as active behavior. Compatibility parsing may exist only when documented and non-authoritative.

- [ ] **Step 5: Diff-review against the source audit.**

Verify:

```text
FAST has zero subprocess acquisition
guest runtime has zero subprocess acquisition
storage runtime has zero subprocess acquisition
full SMART is HEALTH only
.version is SLOW correctness check
NORMAL/DETAIL cannot alter scheduler intervals
missing/invalid/stale never becomes zero
```

- [ ] **Step 6: Commit any final test-only/integration corrections.**

```bash
git add dh_pve_app
 git commit -m "test(dh-pve): verify simplified runtime foundation"
```

If no correction is required, do not create an empty commit.

## Plan boundary

After Task 8, do **not** jump directly to UPS Trigger Policy v2. The next implementation plan covers:

```text
new dh_app_pve_* / dh_app_pve_ups_* Discovery contract
MQTT alert threshold numbers
problem binaries/aggregates/presentation
native MQTT Event notification boundary
coherent transition publication bundle
versioned retained Discovery tombstone migration
```

Only after that Plan 2 is GREEN does Plan 3 implement UPS status/charger/power improvements, scheduled-test beeper restoration, Trigger Policy v2, shutdown-budget integration, HA package/UI and notification delivery.
