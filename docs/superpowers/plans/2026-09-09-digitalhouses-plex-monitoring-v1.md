# DigitalHouses Plex Monitoring v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `digitalhouses_plex_monitoring`, the first DigitalHouses `linux_agent`, to publish trustworthy Plex process activity and adaptive CPU telemetry into Home Assistant through MQTT Device Discovery.

**Architecture:** A native Python 3.11+ systemd service runs beside Plex in the same VM/LXC/Linux host, samples local Plex processes every 10 seconds, classifies Plex Scanner/Transcoder work, computes current and rolling CPU metrics, and publishes retained MQTT state only when activity or load changes meaningfully. Installation/update comes from GitHub through one idempotent `install.sh`; local `.conf` is preserved.

**Tech Stack:** Python 3.11+, standard library, `psutil`, `paho-mqtt` 2.x, `unittest`, Bash, systemd, Home Assistant MQTT Device Discovery.

**Spec:** `docs/superpowers/specs/2026-09-09-digitalhouses-plex-monitoring-design.md`

## Global Constraints

- Application directory is exactly `digitalhouses_plex_monitoring`.
- `digitalhouses.app` contains `type = linux_agent`.
- `VERSION` is the only release-version authority.
- Initial release version is `0.1.0`.
- Production config is `/etc/digitalhouses_plex_monitoring/digitalhouses_plex_monitoring.conf`.
- Installed source is `/opt/digitalhouses/digitalhouses_plex_monitoring/`.
- Persistent runtime path is `/var/lib/digitalhouses_plex_monitoring/`.
- Service is `digitalhouses_plex_monitoring.service`.
- Default `instance_id` is `plex`, producing `dh_plex_*` entity IDs.
- Internal polling default is 10 seconds.
- Rolling CPU window default is 60 seconds.
- CPU uses Linux top-style semantics: 100% = one logical CPU; values >100% are valid.
- CPU significant-change default is 5 percentage points.
- High-load threshold is current total Plex CPU >=80%.
- High-load forced publish interval is 60 seconds.
- No Plex token/API/database dependency in v1.
- No Proxmox API dependency.
- No local history database.
- Current item/process count alone must not cause high-frequency MQTT history.
- MQTT state and Device Discovery are retained.
- Existing native Plex viewer count remains external to this agent.
- Service runs unprivileged by default.
- Tests use `unittest` and must pass together.
- Do not create site-specific IPs, credentials, or Home Assistant entity bindings in reusable source.

---

## File Structure

Create:

```text
digitalhouses_plex_monitoring/
├── digitalhouses.app
├── VERSION
├── README.md
├── CHANGELOG.md
├── requirements.txt
├── install.sh
├── app/
│   ├── __init__.py
│   ├── app.py
│   ├── build_info.py
│   ├── config.py
│   ├── models.py
│   ├── process_collector.py
│   ├── activity_classifier.py
│   ├── metrics.py
│   ├── publish_policy.py
│   ├── discovery.py
│   └── mqtt_bridge.py
├── systemd/
│   └── digitalhouses_plex_monitoring.service
├── examples/
│   └── digitalhouses_plex_monitoring.conf.example
└── tests/
    ├── test_build_info.py
    ├── test_config.py
    ├── test_process_collector.py
    ├── test_activity_classifier.py
    ├── test_metrics.py
    ├── test_publish_policy.py
    ├── test_discovery.py
    └── test_state_payload.py
```

Add the approved design document:

```text
docs/superpowers/specs/2026-09-09-digitalhouses-plex-monitoring-design.md
```

Save this plan as:

```text
docs/superpowers/plans/2026-09-09-digitalhouses-plex-monitoring-v1.md
```

---

### Task 1: Scaffold the Linux agent and configuration contract

**Files:**
- Create: `digitalhouses_plex_monitoring/digitalhouses.app`
- Create: `digitalhouses_plex_monitoring/VERSION`
- Create: `digitalhouses_plex_monitoring/CHANGELOG.md`
- Create: `digitalhouses_plex_monitoring/requirements.txt`
- Create: `digitalhouses_plex_monitoring/app/__init__.py`
- Create: `digitalhouses_plex_monitoring/app/config.py`
- Create: `digitalhouses_plex_monitoring/examples/digitalhouses_plex_monitoring.conf.example`
- Create: `digitalhouses_plex_monitoring/tests/test_config.py`

**Interfaces:**
- Produces `MqttConfig`, `GeneralConfig`, `TelemetryConfig`, `AppConfig`.
- Produces `load_config(path: Path) -> AppConfig`.
- Produces `entity_prefix(instance_id: str) -> str`.

- [ ] **Step 1: Add metadata/version/dependencies**

`digitalhouses.app`:

```text
type = linux_agent
```

`VERSION`:

```text
0.1.0
```

`CHANGELOG.md`:

```markdown
# Changelog

## 0.1.0

- Initial DigitalHouses Plex Monitoring Linux agent.
```

`requirements.txt`:

```text
paho-mqtt>=2.1,<3
psutil>=5.9,<8
```

- [ ] **Step 2: Write failing config tests**

Create tests that require:
- defaults: poll=10, cpu_window=60, cpu delta=5, high load=80, high interval=60;
- required MQTT host;
- `instance_id=plex` maps to `dh_plex`;
- `instance_id=plex_guest` maps to `dh_plex_guest`;
- invalid IDs (`Plex-VM`, `_plex`, `plex.vm`) fail;
- MQTT password containing `=`, `#`, `;` parses without interpolation.

Use a temporary config file and `load_config`.

- [ ] **Step 3: Verify failure**

Run:

```bash
python -m unittest digitalhouses_plex_monitoring.tests.test_config -v
```

Expected: FAIL because `app.config` does not exist.

- [ ] **Step 4: Implement config dataclasses**

Use:

```python
@dataclass(frozen=True)
class GeneralConfig:
    instance_id: str
    instance_name: str
    poll_interval_seconds: float
    cpu_window_seconds: float
    log_level: str

@dataclass(frozen=True)
class TelemetryConfig:
    cpu_change_threshold: float
    high_load_threshold: float
    high_load_publish_interval_seconds: float

@dataclass(frozen=True)
class MqttConfig:
    host: str
    port: int
    username: str
    password: str
    topic_prefix: str
    discovery_prefix: str
    keepalive_seconds: int

@dataclass(frozen=True)
class AppConfig:
    general: GeneralConfig
    telemetry: TelemetryConfig
    mqtt: MqttConfig
```

Use:

```python
configparser.ConfigParser(interpolation=None)
```

Validation:
- instance ID regex `^[a-z0-9][a-z0-9_]*$`;
- port 1..65535;
- poll interval 2..300;
- CPU window >= poll interval;
- thresholds >0;
- keepalive 10..3600;
- log level one of `debug`, `info`, `warning`, `error`.

- [ ] **Step 5: Add example config**

Use the exact defaults from the spec, but set:

```ini
host =
```

so no private broker is committed.

- [ ] **Step 6: Run tests**

```bash
python -m unittest digitalhouses_plex_monitoring.tests.test_config -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add digitalhouses_plex_monitoring
git commit -m "feat(plex): add linux agent configuration contract"
```

---

### Task 2: Define process and monitor models

**Files:**
- Create: `digitalhouses_plex_monitoring/app/models.py`
- Create: `digitalhouses_plex_monitoring/tests/test_state_payload.py`

**Interfaces:**
- `RawProcess`
- `ProcessSample`
- `ActivityState`
- `CpuGroupMetrics`
- `CpuMetrics`
- `BuildInfo`
- `MonitorSnapshot`
- `build_state_payload(snapshot: MonitorSnapshot, build: BuildInfo) -> dict[str, object]`

- [ ] **Step 1: Define exact dataclasses**

Implement:

```python
@dataclass(frozen=True)
class RawProcess:
    pid: int
    create_time: float
    name: str
    cmdline: tuple[str, ...]
    cpu_time_seconds: float

@dataclass(frozen=True)
class ProcessSample:
    pid: int
    create_time: float
    name: str
    cmdline: tuple[str, ...]
    cpu_percent: float

@dataclass(frozen=True)
class ActivityState:
    plex_server_running: bool
    scanner_running: bool
    credits_detection: bool
    intro_detection: bool
    thumbnail_generation: bool
    transcoder_running: bool
    activity: str
    scanner_actions: tuple[str, ...]
    current_item: str | None

@dataclass(frozen=True)
class CpuGroupMetrics:
    current: float
    average: float
    maximum: float

@dataclass(frozen=True)
class CpuMetrics:
    total: CpuGroupMetrics
    scanner: CpuGroupMetrics
    transcoder: CpuGroupMetrics

@dataclass(frozen=True)
class BuildInfo:
    version: str
    source: str
    commit: str

@dataclass(frozen=True)
class MonitorSnapshot:
    collected_at: str
    activity: ActivityState
    cpu: CpuMetrics
    process_count: int
    collector_status: str
    last_refresh: str | None
```

- [ ] **Step 2: Write state-payload tests**

Assert payload keys are exactly stable snake-case names including:

```text
activity
current_item
server_running
scanner_running
credits_detection
intro_detection
thumbnail_generation
transcoder_running
scanner_actions
process_count
collector_status
cpu
cpu_avg
cpu_max
scanner_cpu
scanner_cpu_avg
scanner_cpu_max
transcoder_cpu
transcoder_cpu_avg
transcoder_cpu_max
last_refresh
build_version
build_source
build_commit
```

`current_item=None` maps to string `none`.

`scanner_actions=()` maps to `none`; non-empty joins with commas.

Round CPU output to one decimal place.

- [ ] **Step 3: Implement `build_state_payload`**

Keep serialization in `models.py` so Discovery templates and MQTT payload share one stable state schema.

- [ ] **Step 4: Run**

```bash
python -m unittest digitalhouses_plex_monitoring.tests.test_state_payload -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add digitalhouses_plex_monitoring/app/models.py \
  digitalhouses_plex_monitoring/tests/test_state_payload.py
git commit -m "feat(plex): define stable monitor state schema"
```

---

### Task 3: Collect Plex processes and calculate top-style CPU

**Files:**
- Create: `digitalhouses_plex_monitoring/app/process_collector.py`
- Create: `digitalhouses_plex_monitoring/tests/test_process_collector.py`

**Interfaces:**
- `is_plex_process_name(name: str) -> bool`
- `verify_proc_visibility(path: Path = Path("/proc/1/cmdline")) -> None`
- `collect_raw_processes() -> list[RawProcess]`
- class `CpuSampler`
- `CpuSampler.sample(processes: Sequence[RawProcess], now: float) -> list[ProcessSample]`

- [ ] **Step 1: Write filtering/CPU tests**

Required cases:
- `"Plex Media Server"` true;
- `"Plex Media Scanner"` true;
- `"Plex Transcoder"` true;
- `"plexmediaserver-helper"` true because case-insensitive prefix `plex`;
- `"python3"` false.

CPU test:

First poll at `t=100`, cpu_time=10 → 0%.

Second poll at `t=110`, cpu_time=20.6 → 106.0%.

PID reuse test:
same PID but different `create_time` → treated as a new process and returns 0%.

- [ ] **Step 2: Implement raw collection with psutil**

Use `psutil.process_iter` and request:

```text
pid
name
cmdline
create_time
cpu_times
```

CPU time is:

```python
cpu_times.user + cpu_times.system
```

Ignore processes that disappear between enumeration and inspection.

A global process-enumeration failure raises a collector exception instead of returning an empty list.

- [ ] **Step 3: Implement CPU sampler**

Key previous process state by:

```python
(pid, create_time)
```

For an existing process:

```python
cpu = max(0.0, (cpu_time_now - cpu_time_previous) / (now - previous_now) * 100.0)
```

Do not cap at 100.

- [ ] **Step 4: Add `/proc` visibility check**

Attempt to open/read `/proc/1/cmdline`.

On `PermissionError`, raise a dedicated:

```python
class ProcVisibilityError(RuntimeError):
    pass
```

with a message explaining that the unprivileged agent cannot inspect the process namespace.

- [ ] **Step 5: Run**

```bash
python -m unittest digitalhouses_plex_monitoring.tests.test_process_collector -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add digitalhouses_plex_monitoring/app/process_collector.py \
  digitalhouses_plex_monitoring/tests/test_process_collector.py
git commit -m "feat(plex): collect processes and measure CPU"
```

---

### Task 4: Classify Plex workload

**Files:**
- Create: `digitalhouses_plex_monitoring/app/activity_classifier.py`
- Create: `digitalhouses_plex_monitoring/tests/test_activity_classifier.py`

**Interfaces:**
- `extract_server_actions(cmdline: Sequence[str]) -> tuple[str, ...]`
- `extract_current_item(cmdline: Sequence[str]) -> str | None`
- `classify_activity(processes: Sequence[ProcessSample]) -> ActivityState`

- [ ] **Step 1: Add real Credits fixture**

Test an observed-style scanner command containing:

```text
Plex Media Scanner
--log-file-suffix
Credits
--creditsTempDataPath
/tmp/PlexCreditsDetection-123
/path/to/Mazhor.s2.01.HDTV1080.ts
```

Expected:
- scanner true;
- credits true;
- activity `credits_detection`;
- current item `Mazhor.s2.01.HDTV1080.ts`.

- [ ] **Step 2: Add server-action tests**

Cover:

```text
--server-action credits
--server-action intro
--server-action intros
--server-action index,intro,credits,voiceActivity
--server-action voiceActivity,addetect
```

Normalization output is lowercase:

```text
voiceactivity
addetect
```

Combined index+intro+credits gives:
- credits true;
- intro true;
- thumbnails true;
- activity `multiple`.

- [ ] **Step 3: Add thumbnail and generic scanner tests**

Strong thumbnail signatures:
- `--index`;
- `-b`;
- `--chapter-thumbs-only`;
- `--server-action index`.

Plain:

```text
Plex Media Scanner --generate --section 2
```

must remain generic scanner unless another strong thumbnail signature exists.

- [ ] **Step 4: Add transcoder/multiple tests**

A lone `Plex Transcoder` → `transcoding`.

Scanner + Transcoder → `multiple`.

No Plex Media Server and no other Plex processes → `plex_not_running`.

Plex Media Server only → `idle`.

- [ ] **Step 5: Add current-item fallback tests**

Priority:
1. recognized media basename;
2. `--item 1234` → `item 1234`;
3. `--section 5` → `section 5`;
4. none.

Do not return `PlexCreditsDetection-*` temporary paths as the media item.

- [ ] **Step 6: Implement classifier**

Use case-insensitive process-name comparisons:
- contains `"media server"` for server-running;
- contains `"media scanner"` for scanner;
- contains `"transcoder"` for transcoder.

Normalize command tokens with casefold only for matching; preserve original path text for display basename.

Recognized media extensions must include at minimum:

```text
.mkv .mp4 .m4v .avi .mov .ts .m2ts .mpeg .mpg .webm
.mp3 .flac .m4a .aac .wav .ogg
```

- [ ] **Step 7: Run**

```bash
python -m unittest digitalhouses_plex_monitoring.tests.test_activity_classifier -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add digitalhouses_plex_monitoring/app/activity_classifier.py \
  digitalhouses_plex_monitoring/tests/test_activity_classifier.py
git commit -m "feat(plex): classify Plex scanner and transcoder activity"
```

---

### Task 5: Calculate grouped rolling CPU metrics

**Files:**
- Create: `digitalhouses_plex_monitoring/app/metrics.py`
- Create: `digitalhouses_plex_monitoring/tests/test_metrics.py`

**Interfaces:**
- `group_current_cpu(processes: Sequence[ProcessSample]) -> tuple[float, float, float]`
- class `RollingCpuMetrics`
- `RollingCpuMetrics.update(now: float, total: float, scanner: float, transcoder: float) -> CpuMetrics`

- [ ] **Step 1: Write grouping tests**

Given:
- Plex Media Server 20%;
- Plex Media Scanner 106%;
- Plex Transcoder 40%;
- Python 90% (should never normally reach here, but ignore if not Plex);

Expected:
- total=166;
- scanner=106;
- transcoder=40.

- [ ] **Step 2: Write rolling-window test**

With 60s window and samples:

```text
t=0   total=0
t=10  total=100
t=20  total=50
```

Expected at t=20:
- current 50;
- average 50;
- max 100.

At t=70, after adding total=10, t=0 must be evicted.

Use arithmetic mean of samples inside the window.

- [ ] **Step 3: Implement**

Store a deque of:

```python
(timestamp, total, scanner, transcoder)
```

Evict while:

```python
timestamp < now - window_seconds
```

- [ ] **Step 4: Run**

```bash
python -m unittest digitalhouses_plex_monitoring.tests.test_metrics -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add digitalhouses_plex_monitoring/app/metrics.py \
  digitalhouses_plex_monitoring/tests/test_metrics.py
git commit -m "feat(plex): add rolling CPU telemetry"
```

---

### Task 6: Implement adaptive publication policy

**Files:**
- Create: `digitalhouses_plex_monitoring/app/publish_policy.py`
- Create: `digitalhouses_plex_monitoring/tests/test_publish_policy.py`

**Interfaces:**
- `PublishDecision(publish: bool, reasons: tuple[str, ...])`
- class `PublishPolicy`
- `PublishPolicy.evaluate(snapshot: MonitorSnapshot, now: float, force: bool = False) -> PublishDecision`
- `PublishPolicy.mark_published(snapshot: MonitorSnapshot, now: float) -> None`

- [ ] **Step 1: Write startup/force tests**

No previous publication → publish reason `startup`.

`force=True` → publish reason includes `force`.

- [ ] **Step 2: Write event-transition tests**

Publishing triggers on any change in:

```text
server_running
scanner_running
credits_detection
intro_detection
thumbnail_generation
transcoder_running
activity
scanner_actions
collector_status
```

`current_item` only change → no publish.

`process_count` only change → no publish.

- [ ] **Step 3: Write CPU threshold tests**

Last published total CPU 20:
- new 24.9 → no publish;
- new 25.0 → publish.

Repeat for scanner and transcoder current CPU.

0→0.1 publishes.

0.1→0 publishes.

- [ ] **Step 4: Write high-load tests**

Last current total 79 → new 80 publishes upward crossing.

While >=80:
- 59s since last publish → no forced publish if no other change;
- 60s → publish reason `high_load_interval`.

Last current total 90 → new 79 publishes downward crossing.

Use current total CPU only, not average/max.

- [ ] **Step 5: Implement**

Constructor:

```python
PublishPolicy(
    cpu_change_threshold: float,
    high_load_threshold: float,
    high_load_publish_interval_seconds: float,
)
```

Keep only the last successfully published snapshot/time.

Do not mark a snapshot as published until the MQTT publish call reports success/accepted enqueue.

- [ ] **Step 6: Run**

```bash
python -m unittest digitalhouses_plex_monitoring.tests.test_publish_policy -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add digitalhouses_plex_monitoring/app/publish_policy.py \
  digitalhouses_plex_monitoring/tests/test_publish_policy.py
git commit -m "feat(plex): add adaptive MQTT publication policy"
```

---

### Task 7: Build instance-aware MQTT Device Discovery

**Files:**
- Create: `digitalhouses_plex_monitoring/app/discovery.py`
- Create: `digitalhouses_plex_monitoring/tests/test_discovery.py`

**Interfaces:**
- class `Topics`
- `build_topics(config: AppConfig) -> Topics`
- `build_discovery_payload(config: AppConfig, build: BuildInfo) -> dict[str, object]`

- [ ] **Step 1: Define topic contract**

For default instance:

```text
base = DigitalHouses/Global/plex_monitoring/plex
state = <base>/state
app_availability = <base>/availability
collector_availability = <base>/collector_availability
refresh = <base>/refresh
discovery = homeassistant/device/digitalhouses_plex_monitoring_plex/config
ha_status = homeassistant/status
```

- [ ] **Step 2: Write identity tests**

For `instance_id=plex`, verify exact default entity IDs from the design spec.

For `instance_id=plex_guest`, verify examples:

```text
sensor.dh_plex_guest_activity
sensor.dh_plex_guest_cpu
binary_sensor.dh_plex_guest_credits_detection
button.dh_plex_guest_refresh
```

Unique IDs must include:

```text
digitalhouses_plex_monitoring_<instance_id>_<component>
```

- [ ] **Step 3: Write availability tests**

Process-derived components require both:
- app availability;
- collector availability;

with `availability_mode = all`.

Diagnostic build, collector-status, and refresh button require only app availability.

- [ ] **Step 4: Implement device payload**

Device:

```python
{
    "identifiers": [device_id],
    "name": config.general.instance_name,
    "manufacturer": "DigitalHouses",
    "model": "Linux Plex Workload Monitor",
    "sw_version": build.version,
}
```

Origin support URL:

```text
https://github.com/DigitalHouses/home-assistant-apps/tree/main/digitalhouses_plex_monitoring
```

CPU sensors:
- `%`;
- `state_class="measurement"`;
- `suggested_display_precision=1`.

Build sensor:
- state template from `build_commit_short`;
- JSON attributes for version/source/full commit.

Refresh button:
- payload `PRESS`.

- [ ] **Step 5: Run**

```bash
python -m unittest digitalhouses_plex_monitoring.tests.test_discovery -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add digitalhouses_plex_monitoring/app/discovery.py \
  digitalhouses_plex_monitoring/tests/test_discovery.py
git commit -m "feat(plex): add Home Assistant MQTT discovery"
```

---

### Task 8: Add build identity and MQTT bridge

**Files:**
- Create: `digitalhouses_plex_monitoring/app/build_info.py`
- Create: `digitalhouses_plex_monitoring/app/mqtt_bridge.py`
- Create: `digitalhouses_plex_monitoring/tests/test_build_info.py`

**Interfaces:**
- `load_build_info(app_root: Path) -> BuildInfo`
- class `MqttBridge`
- events: `refresh_requested`, `republish_requested`, `wake_requested`
- methods: `start()`, `stop()`, `publish_discovery()`, `publish_state(payload)`, `set_collector_available(bool)`

- [ ] **Step 1: Define build-info file format**

Installer-generated:

```text
BUILD_INFO
```

Content:

```text
version = 0.1.0
source = main
commit = 0123456789abcdef0123456789abcdef01234567
```

Use the same flat `key = value` concept; do not use INI sections.

If `BUILD_INFO` is absent in a developer checkout:
- version from `VERSION`;
- source=`local`;
- commit=`unknown`.

- [ ] **Step 2: Test build parsing/fallback**

Write tests for complete build info, missing build info, malformed missing commit.

- [ ] **Step 3: Implement MQTT bridge with Paho callback API v2**

Use:

```python
mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=device_id)
```

Set retained LWT on app availability:

```text
offline
```

On connect:
- subscribe HA status;
- subscribe refresh command;
- publish app availability online retained;
- set `republish_requested`;
- wake main loop.

On message:
- HA `online` → republish event + wake;
- refresh `PRESS` → refresh event + wake.

Callbacks must not run the collector.

- [ ] **Step 4: Publishing rules**

Discovery retained.

State retained.

Collector availability retained.

On graceful stop:
- publish app availability offline retained;
- disconnect;
- stop network loop.

Never log username/password.

- [ ] **Step 5: Run build tests and compile**

```bash
python -m unittest digitalhouses_plex_monitoring.tests.test_build_info -v
python -m compileall -q digitalhouses_plex_monitoring/app
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add digitalhouses_plex_monitoring/app/build_info.py \
  digitalhouses_plex_monitoring/app/mqtt_bridge.py \
  digitalhouses_plex_monitoring/tests/test_build_info.py
git commit -m "feat(plex): add build identity and MQTT transport"
```

---

### Task 9: Orchestrate the monitor loop

**Files:**
- Create: `digitalhouses_plex_monitoring/app/app.py`
- Modify: `digitalhouses_plex_monitoring/app/models.py`
- Add tests where pure orchestration helpers are extracted.

**Interfaces:**
- `build_snapshot(...) -> MonitorSnapshot`
- `main() -> int`

- [ ] **Step 1: Add argument parsing**

Support:

```text
--config /etc/digitalhouses_plex_monitoring/digitalhouses_plex_monitoring.conf
```

Default to the canonical path.

- [ ] **Step 2: Configure logging**

Map configured level.

Log startup:

```text
DigitalHouses Plex Monitoring 0.1.0
Source: main
Commit: <short>
Instance: plex
Poll interval: 10s
CPU window: 60s
```

- [ ] **Step 3: Initialize**

Order:
1. config;
2. build info;
3. `/proc` visibility verification;
4. CPU sampler;
5. rolling metrics;
6. publish policy;
7. MQTT bridge;
8. signals;
9. start MQTT.

- [ ] **Step 4: Implement one collection cycle**

Each cycle:
1. collect raw Plex processes;
2. CPU-sample;
3. classify;
4. group CPU;
5. update rolling metrics;
6. construct timestamped snapshot;
7. set collector availability online;
8. evaluate policy;
9. if publish, build payload and publish retained;
10. mark policy only after publish accepted.

- [ ] **Step 5: Implement collector error transition**

On collection exception:
- log exception once per transition plus DEBUG details thereafter;
- publish collector availability offline;
- publish state with `collector_status=error` and last known process metrics;
- do not label activity as idle;
- continue retrying at the normal poll interval.

On next success:
- publish collector availability online;
- force full snapshot with status `ok`.

- [ ] **Step 6: Implement manual refresh**

When `refresh_requested`:
- clear/coalesce event;
- collect immediately;
- set `last_refresh` only if collection succeeds;
- force full publish.

- [ ] **Step 7: Implement reconnect/HA birth**

When `republish_requested`:
- publish Discovery;
- force current snapshot if one exists;
- if no successful snapshot yet, Discovery can still publish and state waits for first collection.

- [ ] **Step 8: Implement timing/wakeup**

Use an event wait rather than unconditional `sleep` so MQTT refresh/HA birth can wake the loop.

Maintain monotonic next-poll timing.

- [ ] **Step 9: Signals**

SIGTERM/SIGINT:
- set stop event;
- wake loop;
- graceful MQTT offline/disconnect;
- return 0.

- [ ] **Step 10: Run full Python suite**

```bash
python -m unittest discover -s digitalhouses_plex_monitoring/tests -v
python -m compileall -q digitalhouses_plex_monitoring/app digitalhouses_plex_monitoring/tests
```

Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add digitalhouses_plex_monitoring/app \
  digitalhouses_plex_monitoring/tests
git commit -m "feat(plex): orchestrate monitoring service"
```

---

### Task 10: Create systemd service and idempotent GitHub installer

**Files:**
- Create: `digitalhouses_plex_monitoring/systemd/digitalhouses_plex_monitoring.service`
- Create: `digitalhouses_plex_monitoring/install.sh`
- Add installer contract checks to tests if repository standard provides Linux-agent validator.

**Interfaces:**
- user `digitalhouses_plex_monitoring`;
- config root:service-group `0640`;
- state service-user:service-group;
- source root-owned;
- `DIGITALHOUSES_SOURCE_REF` defaults `main`.

- [ ] **Step 1: Create systemd unit**

Use:

```ini
[Unit]
Description=DigitalHouses Plex Monitoring
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=digitalhouses_plex_monitoring
Group=digitalhouses_plex_monitoring
WorkingDirectory=/opt/digitalhouses/digitalhouses_plex_monitoring
ExecStart=/opt/digitalhouses/digitalhouses_plex_monitoring/.venv/bin/python -m app.app --config /etc/digitalhouses_plex_monitoring/digitalhouses_plex_monitoring.conf
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/digitalhouses_plex_monitoring

[Install]
WantedBy=multi-user.target
```

Do not enable process-hiding systemd options.

- [ ] **Step 2: Installer constants**

Use:

```bash
APP_NAME="digitalhouses_plex_monitoring"
SERVICE_NAME="digitalhouses_plex_monitoring.service"
SERVICE_USER="digitalhouses_plex_monitoring"
REPO_URL="https://github.com/DigitalHouses/home-assistant-apps.git"
SOURCE_REF="${DIGITALHOUSES_SOURCE_REF:-main}"
APP_DIR="/opt/digitalhouses/${APP_NAME}"
CONFIG_DIR="/etc/${APP_NAME}"
CONFIG_FILE="${CONFIG_DIR}/${APP_NAME}.conf"
STATE_DIR="/var/lib/${APP_NAME}"
```

Require root.

- [ ] **Step 3: Install prerequisites only when missing**

On Debian/Ubuntu require:
- `git`;
- `python3`;
- `python3 -m venv`;
- CA certificates.

If `apt-get` is unavailable and prerequisites are missing, fail clearly instead of guessing another distro's package manager.

- [ ] **Step 4: Fetch exact source**

Clone repository into `mktemp -d`, fetch/checkout `SOURCE_REF`, then:

```bash
git rev-parse HEAD
```

Capture full SHA.

Copy only:

```text
digitalhouses_plex_monitoring/
```

into canonical `APP_DIR`.

Preserve `.venv` if already present; remove stale installed source files before copying new source.

Always clean the temporary clone with `trap`.

- [ ] **Step 5: Create service account/directories**

Create system user/group without login shell/home when absent.

Permissions:

```text
/opt/...                         root:root 0755
/etc/app                         root:service-group 0750
/etc/app/app.conf                root:service-group 0640
/var/lib/app                     service-user:service-group 0750
```

- [ ] **Step 6: First config prompts**

Only if config absent.

Read from `/dev/tty`.

Defaults:
- instance ID `plex`;
- instance name `DH Plex`;
- MQTT port `1883`.

MQTT host must be non-empty.

Write config with `printf`, not a shell heredoc.

Do not echo password.

- [ ] **Step 7: Create/update venv**

```bash
python3 -m venv "${APP_DIR}/.venv"
"${APP_DIR}/.venv/bin/python" -m pip install --disable-pip-version-check --upgrade pip
"${APP_DIR}/.venv/bin/python" -m pip install --disable-pip-version-check -r "${APP_DIR}/requirements.txt"
```

- [ ] **Step 8: Write BUILD_INFO**

Read release from `${APP_DIR}/VERSION`.

Write:

```text
version = <version>
source = <SOURCE_REF>
commit = <full_sha>
```

root-owned, readable by service.

- [ ] **Step 9: Install/restart service**

Copy unit to:

```text
/etc/systemd/system/digitalhouses_plex_monitoring.service
```

Then:

```bash
systemctl daemon-reload
systemctl enable digitalhouses_plex_monitoring.service
systemctl restart digitalhouses_plex_monitoring.service
systemctl is-active --quiet digitalhouses_plex_monitoring.service
```

If inactive:
- print `systemctl status ... --no-pager`;
- print last 50 journal lines;
- exit non-zero.

- [ ] **Step 10: Shell/systemd validation**

```bash
bash -n digitalhouses_plex_monitoring/install.sh
systemd-analyze verify digitalhouses_plex_monitoring/systemd/digitalhouses_plex_monitoring.service
```

Where systemd verify is supported.

- [ ] **Step 11: Commit**

```bash
git add digitalhouses_plex_monitoring/install.sh \
  digitalhouses_plex_monitoring/systemd
git commit -m "feat(plex): add GitHub installer and systemd service"
```

---

### Task 11: Documentation and first-host smoke test

**Files:**
- Create: `digitalhouses_plex_monitoring/README.md`
- Ensure design/plan documents are committed.
- Modify `CHANGELOG.md` only if implementation behavior changed from the initial entry.

**Interfaces:**
- README is the operator contract.

- [ ] **Step 1: Document one-command install/update**

Include:

```bash
curl -fsSL https://raw.githubusercontent.com/DigitalHouses/home-assistant-apps/main/digitalhouses_plex_monitoring/install.sh | sudo bash
```

Also document root-shell equivalent without `sudo`.

Explain rerunning the same command updates from current `main`.

- [ ] **Step 2: Document config and commands**

```bash
systemctl status digitalhouses_plex_monitoring
journalctl -u digitalhouses_plex_monitoring -f
```

Config path and each option.

Explain CPU semantics (>100% valid).

Explain native Plex integration remains responsible for viewer count.

- [ ] **Step 3: Document entities**

List every entity from the design spec.

Explain:
- current item is sampled only on meaningful publishes;
- scanner actions may show future unknown actions;
- transcoder-running does not prove playback transcoding.

- [ ] **Step 4: Run complete CI-equivalent checks**

```bash
python -m compileall -q \
  digitalhouses_plex_monitoring/app \
  digitalhouses_plex_monitoring/tests

python -m unittest discover \
  -s digitalhouses_plex_monitoring/tests -v

bash -n digitalhouses_plex_monitoring/install.sh

systemd-analyze verify \
  digitalhouses_plex_monitoring/systemd/digitalhouses_plex_monitoring.service
```

Run repository validator from the concurrently-updated application standard if it is already merged:

```bash
python scripts/validate_repository.py
```

If the standard work is not merged yet, do not weaken Plex to satisfy the old Speedtest-only validator; merge/rebase the standard foundation first.

- [ ] **Step 5: Install on the real Plex VM**

On the current VM-based Plex host, run the one-line installer.

Verify:

```bash
systemctl is-active digitalhouses_plex_monitoring
journalctl -u digitalhouses_plex_monitoring -n 100 --no-pager
```

In Home Assistant verify one device and all expected entities.

- [ ] **Step 6: Exercise manual refresh**

Press:

```text
button.dh_plex_refresh
```

Verify:
- immediate log entry;
- `sensor.dh_plex_last_refresh` changes;
- full state republishes.

- [ ] **Step 7: Exercise known Credits workload**

During a real Plex Credits Detection task verify:
- scanner running ON;
- credits detection ON;
- activity credits_detection or multiple;
- current item best-effort value;
- Scanner and total Plex CPU rise;
- high-load cadence works if >=80%.

Do not artificially force a long 2160→1080 transcode solely for the test unless needed.

- [ ] **Step 8: Correlate one historical window**

Use HA history with existing:
- Proxmox CPU temperature;
- thermal throttling;
- Plex VM CPU;
- disk temperatures;
- native `sensor.plex_vm`.

Confirm the Plex entities explain the workload timeline.

- [ ] **Step 9: Commit docs**

```bash
git add digitalhouses_plex_monitoring/README.md \
  digitalhouses_plex_monitoring/CHANGELOG.md \
  docs/superpowers/specs/2026-09-09-digitalhouses-plex-monitoring-design.md \
  docs/superpowers/plans/2026-09-09-digitalhouses-plex-monitoring-v1.md
git commit -m "docs(plex): document installation and monitoring contract"
```

---

## Completion Gate

v1 is complete only when:

```text
type                                  linux_agent
VERSION                               0.1.0
config extension                      .conf
service                               unprivileged systemd
VM/LXC logic                          identical
Plex API token                        not required
internal poll                         10s
CPU change threshold                  5 percentage points
high load                             current total Plex CPU >=80%
high-load publish interval            60s
current-item-only change              does not publish
process-count-only change             does not publish
startup/reconnect/HA birth/refresh    full publish
state/discovery                       retained
collector failure                     cannot masquerade as idle
Credits observed command              classified
generic unknown scanner               visible
CPU >100%                             preserved
manual refresh                        verified
real Plex VM smoke test               passed
```

## Self-Review

**Spec coverage:** Project structure, Linux filesystem/config/service contracts, Git source identity, process collection, CPU semantics, Credits/Intro/thumbnail/transcoder classification, unknown-action fallback, current-item anti-spam behavior, collector availability, MQTT topology, Discovery entities, adaptive publishing, Refresh, installation/update, journald, unprivileged service, tests, and first-host verification are all mapped to implementation tasks.

**Deliberate deferrals:** Plex API/session details, playback normalization package, and final cross-system dashboard are not part of the agent core. The native Plex integration supplies viewer count; dashboard work follows after real v1 entity verification.

**No hidden version source:** `VERSION` is authoritative; `BUILD_INFO` only records installed source identity.

**No false precision:** The classifier only asserts known activities from strong process arguments. Unknown scanner work remains visible as generic scanner activity and raw normalized scanner actions.
