# DigitalHouses Plex Monitoring v1 — Design Specification

**Date:** 2026-09-09
**Status:** Approved architecture / implementation-ready
**Application type:** `linux_agent`
**Repository:** `DigitalHouses/home-assistant-apps`

## 1. Purpose

`digitalhouses_plex_monitoring` is a native Linux workload monitor for Plex Media Server.

The primary use case is historical diagnosis in Home Assistant:

> Open a time window and determine what Plex was doing when host CPU temperature, VM/LXC CPU, GPU/video load, storage temperature, or thermal throttling changed.

The monitor intentionally complements existing host/Proxmox telemetry. It does not duplicate general hardware monitoring.

## 2. Runtime model

The agent runs in the same Linux process namespace as Plex Media Server:

```text
Plex in VM / LXC / bare Linux
        ↓
local /proc + psutil
        ↓
digitalhouses_plex_monitoring
        ↓
MQTT Device Discovery
        ↓
Home Assistant Recorder
```

The agent must not use Proxmox API, `qm`, `pct`, Docker host PID tricks, or HAOS Supervisor APIs.

Initial supported operating systems are Debian/Ubuntu-family Linux installations where Plex runs as a native service.

## 3. v1 non-goals

- No Plex token.
- No Plex HTTP API dependency.
- No viewer/user/media-session duplication.
- No local history database.
- No Proxmox dependency.
- No Docker distribution.
- No attempt to identify Direct Play vs Direct Stream from Plex API.
- No attempt to resolve a Plex numeric rating key to a title through the Plex database.

The native Home Assistant Plex integration remains the source for concurrent playback count. On the current site that is `sensor.plex_vm`.

## 4. DigitalHouses Linux-agent contract

Project name:

```text
digitalhouses_plex_monitoring
```

Metadata:

```text
type = linux_agent
```

Canonical installed layout:

```text
/opt/digitalhouses/digitalhouses_plex_monitoring/
/etc/digitalhouses_plex_monitoring/digitalhouses_plex_monitoring.conf
/var/lib/digitalhouses_plex_monitoring/
journald
```

Service:

```text
digitalhouses_plex_monitoring.service
```

Configuration extension is `.conf`.

The service runs under a dedicated unprivileged user:

```text
digitalhouses_plex_monitoring
```

Configuration is owned by `root:digitalhouses_plex_monitoring` with mode `0640`.

## 5. GitHub installation model

GitHub is the source of truth.

Normal development installation/update uses `main` without requiring the operator to select versions.

User-facing installation command:

```bash
curl -fsSL https://raw.githubusercontent.com/DigitalHouses/home-assistant-apps/main/digitalhouses_plex_monitoring/install.sh | sudo bash
```

The same command is used for:
- first install;
- reinstall;
- update.

The installer is idempotent and must preserve the existing production `.conf`.

The installer accepts:

```text
DIGITALHOUSES_SOURCE_REF
```

with default:

```text
main
```

so a later release/tag may be installed without changing the workflow.

Installed build identity must preserve:

```text
Release version
Source ref
Exact Git commit SHA
```

Runtime does not require the installed directory to remain a live Git working tree.

## 6. Python/runtime dependencies

Minimum Python:

```text
Python 3.11
```

Runtime Python dependencies:

```text
paho-mqtt>=2.1,<3
psutil>=5.9,<8
```

All other functionality uses the Python standard library.

## 7. Configuration

Canonical file:

```text
/etc/digitalhouses_plex_monitoring/digitalhouses_plex_monitoring.conf
```

Format:

```ini
[general]
instance_id = plex
instance_name = DH Plex
poll_interval_seconds = 10
cpu_window_seconds = 60
log_level = info

[telemetry]
cpu_change_threshold = 5
high_load_threshold = 80
high_load_publish_interval_seconds = 60

[mqtt]
host = 192.168.1.10
port = 1883
username =
password =
topic_prefix = DigitalHouses/Global/plex_monitoring
discovery_prefix = homeassistant
keepalive_seconds = 60
```

`instance_id`:
- defaults to `plex`;
- must match `^[a-z0-9][a-z0-9_]*$`;
- forms the MQTT instance namespace and Home Assistant entity prefix.

Default entity prefix:

```text
instance_id = plex
→ dh_plex
```

Example second server:

```text
instance_id = plex_guest
→ dh_plex_guest
```

The installer asks only for first-install values when no config exists:
- instance ID, default `plex`;
- instance name, default `DH Plex`;
- MQTT host;
- MQTT port, default `1883`;
- MQTT username, optional;
- MQTT password, optional.

Interactive reads must use `/dev/tty` so they work when the installer itself is piped from `curl`.

## 8. Process collection

Internal process polling default:

```text
10 seconds
```

The collector reads local processes with `psutil`.

A raw process record contains:

```text
pid
create_time
name
cmdline
cpu_time_seconds
```

Plex process inclusion rule:

```text
process name begins with "Plex" (case-insensitive)
```

This includes Plex Media Server, Plex Media Scanner, Plex Transcoder, and relevant helper processes without maintaining a brittle complete executable list.

Before normal monitoring, the collector verifies that an unprivileged service can read ordinary `/proc/<pid>/cmdline` data. If process visibility is restricted, the collector reports failure instead of silently reporting Plex as idle.

## 9. CPU semantics

CPU is calculated from process CPU-time deltas between polls:

```text
cpu_percent = delta_process_cpu_seconds / delta_wall_seconds * 100
```

Semantics intentionally match Linux `top`/`ps` style:

```text
100% = one fully utilized logical CPU
```

Therefore a process/group may exceed 100% on a multi-vCPU Plex VM/LXC.

This is not normalized to the total guest CPU capacity.

CPU groups:

```text
total Plex
Plex Media Scanner
Plex Transcoder
```

For each group expose:
- current CPU over the most recent poll interval;
- rolling average over the last 60 seconds;
- rolling maximum over the last 60 seconds.

The rolling window is based on internal 10-second samples and is independent of MQTT publication frequency.

## 10. Activity classification

Required activity booleans:

```text
plex_server_running
scanner_running
credits_detection
intro_detection
thumbnail_generation
transcoder_running
```

Required summary states:

```text
plex_not_running
idle
scanner
credits_detection
intro_detection
thumbnail_generation
transcoding
multiple
```

Multiple simultaneous activities must never be collapsed into a false single activity. The dedicated binary sensors are authoritative; `activity=multiple` is only a human summary.

### Credits Detection

Recognize if a Plex Media Scanner command contains any strong Credits signature, including:

```text
--server-action ...credits...
--creditsTempDataPath
Credits-specific log suffix
```

### Intro Detection

Recognize `intro` and `intros` action variants:

```text
--server-action intro
--server-action intros
```

including comma-separated action lists.

### Thumbnail generation

Recognize strong thumbnail/index signatures:

```text
--server-action index
--index
-b
--chapter-thumbs-only
```

A plain generic `--generate` without a stronger thumbnail signature is not enough by itself to assert video-preview thumbnail generation.

### Generic Scanner

Any Plex Media Scanner process that is not confidently assigned to a specific subtype remains:

```text
scanner_running = true
activity = scanner
```

This fallback is mandatory.

### Transcoder

A process whose name identifies Plex Transcoder sets:

```text
transcoder_running = true
```

The agent calls this "transcoder running", not "playback transcoding", because background Plex analysis may also use transcoding helpers.

## 11. Scanner action diagnostics

The scanner parser extracts `--server-action` values, lowercases them, splits comma-separated actions, normalizes them, and publishes a diagnostic action string.

Examples:

```text
credits
intro
index,intro,credits,voiceactivity
voiceactivity,addetect
none
```

Unknown future actions remain visible rather than being discarded.

## 12. Current item extraction

No Plex API/database lookup is used.

Best-effort item selection order:

1. media path from explicit file/directory arguments;
2. command-line argument with a recognized media-file extension;
3. `--item <rating_key>` → `item <rating_key>`;
4. `--section <id>` → `section <id>`;
5. `none`.

For a path, publish only a concise basename, not the full filesystem path.

`current_item` is updated internally every poll but does **not** independently trigger an MQTT publish. It is included in every publish caused by an activity transition, CPU change/high-load rule, startup, reconnect, or manual refresh. This prevents a fast library scan from producing one Recorder row per media file while still capturing the item associated with interesting workload events.

## 13. Collector availability

Agent availability and process-collector availability are separate:

```text
.../<instance>/availability
.../<instance>/collector_availability
```

Application availability means the agent/MQTT client is alive.

Collector availability means local Plex process inspection is trustworthy.

Process-derived entities require both availability topics.

If collection fails:
- application availability remains `online`;
- collector availability becomes `offline`;
- diagnostic collector status becomes `error`;
- stale process metrics must not be presented as current.

If Plex itself is simply stopped:
- collector availability remains `online`;
- `plex_server_running = false`;
- `activity = plex_not_running`;
- CPU metrics are zero.

## 14. MQTT topology

Default instance:

```text
DigitalHouses/Global/plex_monitoring/plex/state
DigitalHouses/Global/plex_monitoring/plex/availability
DigitalHouses/Global/plex_monitoring/plex/collector_availability
DigitalHouses/Global/plex_monitoring/plex/refresh
```

Home Assistant:

```text
homeassistant/device/digitalhouses_plex_monitoring_plex/config
homeassistant/status
```

Device identifier:

```text
digitalhouses_plex_monitoring_<instance_id>
```

State and Discovery are retained.

Application availability uses MQTT Last Will.

The client subscribes to:
- `homeassistant/status`;
- the instance refresh command topic.

When Home Assistant announces `online`, Discovery and current retained state are republished.

## 15. Home Assistant entity model

For the default `instance_id = plex`:

### Core state

```text
sensor.dh_plex_activity
sensor.dh_plex_current_item

binary_sensor.dh_plex_server_running
binary_sensor.dh_plex_scanner_running
binary_sensor.dh_plex_credits_detection
binary_sensor.dh_plex_intro_detection
binary_sensor.dh_plex_thumbnail_generation
binary_sensor.dh_plex_transcoder_running
```

### CPU

```text
sensor.dh_plex_cpu
sensor.dh_plex_cpu_avg
sensor.dh_plex_cpu_max

sensor.dh_plex_scanner_cpu
sensor.dh_plex_scanner_cpu_avg
sensor.dh_plex_scanner_cpu_max

sensor.dh_plex_transcoder_cpu
sensor.dh_plex_transcoder_cpu_avg
sensor.dh_plex_transcoder_cpu_max
```

CPU units:

```text
%
```

State class:

```text
measurement
```

Suggested display precision:

```text
1
```

### Diagnostics

```text
sensor.dh_plex_scanner_actions
sensor.dh_plex_process_count
sensor.dh_plex_collector_status
sensor.dh_plex_build
sensor.dh_plex_last_refresh
button.dh_plex_refresh
```

`dh_plex_build` state is the short commit SHA and attributes contain:
- release version;
- source ref;
- full commit SHA.

Build attributes are acceptable because they are static diagnostics, not high-frequency history.

## 16. Adaptive publication policy

Internal polling:

```text
10 seconds
```

MQTT publication is not fixed to the poll interval.

### Always publish a full snapshot

- application startup after MQTT connection;
- MQTT reconnect;
- Home Assistant birth (`homeassistant/status = online`);
- manual Refresh;
- recovery from collector error;
- collector failure status transition.

### Publish immediately on discrete activity change

Examples:
- Plex server starts/stops;
- scanner starts/stops;
- Credits starts/stops;
- Intro starts/stops;
- thumbnail generation starts/stops;
- transcoder starts/stops;
- summary activity changes;
- scanner action set changes.

`process_count` alone does not trigger a publish.

`current_item` alone does not trigger a publish.

### CPU significant-change rule

Compare current CPU for:
- total Plex;
- Scanner;
- Transcoder.

Below high load, publish when any current CPU value changes by at least:

```text
5 percentage points
```

from its last published value.

Always publish current CPU transitions:

```text
0 → non-zero
non-zero → 0
```

### High-load rule

High-load threshold applies to **current total Plex CPU**, not the rolling average:

```text
80%
```

Publish:
- immediately when crossing from below 80% to >=80%;
- at least once every 60 seconds while current total Plex CPU remains >=80%;
- immediately when crossing back below 80%.

The published snapshot also includes the rolling averages/maxima and current item at that moment.

## 17. Manual Refresh

MQTT button:

```text
button.dh_plex_refresh
```

Command payload:

```text
PRESS
```

The MQTT callback does not collect processes directly. It signals the main monitoring loop.

Refresh behavior:
1. wake monitoring loop;
2. collect immediately;
3. update rolling metrics;
4. set `last_refresh` to the successful refresh timestamp;
5. publish a full retained snapshot.

Duplicate refresh requests while one refresh is pending/running may be coalesced.

## 18. Main-loop behavior

The main thread owns collection and state construction.

MQTT callbacks only set thread-safe events.

Conceptual loop:

```text
poll or wake
  ↓
collect processes
  ↓
calculate CPU deltas
  ↓
classify activity
  ↓
update rolling window
  ↓
build snapshot
  ↓
publication policy
  ↓
publish if required
```

On graceful shutdown:
- publish application availability `offline`;
- stop MQTT loop.

## 19. Installer behavior

The installer requires root privileges.

If prerequisites are absent on Debian/Ubuntu, install only what is required:

```text
git
python3
python3-venv
ca-certificates
```

First install:
1. resolve Git source ref;
2. obtain exact repository commit;
3. copy only `digitalhouses_plex_monitoring` into the canonical `/opt` path;
4. create/update virtualenv;
5. install `requirements.txt`;
6. create service user/group;
7. create `/etc` and `/var/lib` paths;
8. create `.conf` only if absent;
9. write build identity;
10. install systemd unit;
11. daemon-reload;
12. enable/start service;
13. verify service is active.

Update:
- preserve `.conf`;
- replace application source with source from requested Git ref;
- update dependencies;
- update build identity/systemd unit;
- restart service;
- verify service.

The installer never stores site-specific configuration in Git.

## 20. systemd security model

Unit uses:

```text
User=digitalhouses_plex_monitoring
Group=digitalhouses_plex_monitoring
```

Recommended hardening:

```text
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/digitalhouses_plex_monitoring
```

Do not use systemd process-visibility hardening that would hide the Plex process namespace from the monitor.

## 21. Logging

All runtime logs go to journald.

Normal operations log at INFO:
- startup/build identity;
- MQTT connect/disconnect;
- collector recovery/failure;
- activity transitions;
- high-load threshold transitions;
- manual refresh;
- clean shutdown.

Do not log MQTT passwords or secrets.

DEBUG may log classification detail and sampled process metadata, but must avoid unnecessarily dumping full sensitive command lines.

## 22. Required tests

Unit tests must cover:

### Configuration
- defaults;
- invalid instance ID;
- required MQTT host;
- numeric ranges;
- password parsing with special characters.

### Process/CPU
- Plex process filtering;
- PID reuse via `(pid, create_time)`;
- first sample produces zero CPU;
- deterministic CPU delta;
- >100% process/group CPU is preserved;
- exited processes disappear cleanly.

### Classification
- observed Credits command with `--creditsTempDataPath`;
- `--server-action credits`;
- `intro` and `intros`;
- comma action lists;
- `index`;
- `--chapter-thumbs-only`;
- generic scanner fallback;
- transcoder;
- simultaneous scanner + transcoder → `multiple`;
- unknown server actions remain visible;
- current media basename;
- item-ID fallback.

### Rolling metrics
- 60-second average;
- 60-second maximum;
- old sample eviction.

### Publish policy
- startup;
- discrete activity transition;
- CPU delta <5 does not publish;
- CPU delta >=5 publishes;
- 0↔non-zero publishes;
- 80% upward crossing;
- 60-second high-load forced publish;
- downward crossing;
- current-item-only change does not publish;
- process-count-only change does not publish;
- force refresh publishes.

### MQTT Discovery
- instance-aware device/topic/unique IDs;
- default entity IDs for `instance_id=plex`;
- dual availability for process-derived entities;
- refresh button;
- retained state/discovery expectations.

### Build/installer contract
- `VERSION` / CHANGELOG consistency;
- build metadata parsing;
- installer shell syntax;
- systemd unit syntax where CI supports it.

## 23. Dashboard integration

The first agent release does not hard-code site host-temperature/GPU/disk entity IDs.

After the agent is running and real entities are verified, the Plex dashboard should correlate synchronized history from:

```text
native Plex viewer count: sensor.plex_vm
Plex activity/binaries
Plex CPU current/avg/max
Proxmox VM CPU
host CPU temperature
thermal throttling
GPU/video load
NVMe/SSD/HDD temperatures
```

A later optional local/passport Home Assistant package may normalize `sensor.plex_vm` into:
- `sensor.dh_plex_playback_count`;
- `binary_sensor.dh_plex_playback_active`.

This mapping is site-local and is not a Linux-agent dependency.

## 24. v1 acceptance scenario

A historical high-temperature incident should be reconstructable approximately as:

```text
02:23  credits_detection = ON
       activity = credits_detection
       current_item = Mazhor.s2.01.HDTV1080.ts

02:24  Plex CPU current = 106%
       Plex CPU max = 109%

02:25  Host CPU temp = 94°C
       Thermal throttling = ON

02:28  credits_detection = OFF
       Plex CPU current = 3%

02:30  Host CPU temp = 81°C
```

The exact hardware temperature/throttle entities come from existing host monitoring; the Plex agent supplies the missing causal workload timeline.
