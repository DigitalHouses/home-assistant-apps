# DH PVE PVE 8.x Source Audit

Date: 2026-09-15
Status: frozen source contract for implementation
Canonical design: `docs/superpowers/specs/2026-09-15-dh-pve-simplified-runtime-haos-design.md`
Audited branch/head before this document: `design/dh-pve-observability-ups-trigger-v2` / `b61f0be409ab047a4ce6e3277d6ac8753a8cf2db`
Target runtime: Proxmox VE 8.x

## Purpose

This audit maps every material runtime field from its current acquisition path to the target cheap source before production code is changed.

The governing source priority is:

```text
/proc, /sys
-> /etc/pve configuration and PVE-maintained status/cache
-> subprocess only where no cheap equivalent satisfies the contract
-> pvesh/API only for rare/on-demand/actions
```

A failed cheap source must never silently become a permanent `pvesh` / `qm` / `pct` / `pvesm` polling loop.

## PVE 8.x cache contract verified against upstream

Proxmox `pvestatd` on PVE 8 maintains current node, QEMU, LXC and storage status and broadcasts it through pmxcfs every approximately 10 seconds. The relevant PVE 8 RRD/status keys are:

```text
pve2-node/<node>
pve2.3-vm/<vmid>
pve2-storage/<node>/<storage-id>
```

For PVE 8, the status payloads consumed by this app are:

```text
pve2-node/<node>:
  uptime, subscription, ctime, loadavg1, maxcpu, cpu, iowait,
  memtotal, memused, swaptotal, swapused, roottotal, rootused,
  netin, netout

pve2.3-vm/<vmid>:
  uptime, name, status, template, ctime, cpus, cpu,
  maxmem, mem, maxdisk, disk, netin, netout, diskread, diskwrite

pve2-storage/<node>/<storage-id>:
  ctime, total, used
```

`/etc/pve/.rrd` is therefore the preferred PVE-maintained status cache for SLOW guest/storage runtime reads. `/etc/pve/.vmlist` supplies VMID ownership/type/version, not live guest status. `/etc/pve/.version` is the cheap change detector for STATIC/configuration refresh.

Target parsers are PVE-8-specific and fixture-tested. Unknown future keys/extra columns are ignored; required PVE 8 columns are validated. `U`, missing, malformed or stale values become unavailable/invalid, never numeric zero.

---

## 1. CPU usage

```text
CURRENT FIELD       cpu.usage_percent
CURRENT SOURCE      /proc/stat delta
CURRENT COST        very low, no subprocess
TARGET CHEAP SOURCE /proc/stat delta
PARSER/FIXTURE      aggregate `cpu` row; monotonic total/idle counters; invalid delta -> None
SUBPROCESS REMAINS  no
CADENCE              FAST 10s
RECORDER             yes
PROBLEM/EVENT        profile decision input; no alert problem by itself unless separately designed
```

Decision window: rolling 60 s. Missing samples are excluded.

## 2. CPU temperature

```text
CURRENT FIELD       cpu.temperature_c
CURRENT SOURCE      /sys/class/hwmon coretemp; x86_pkg_temp thermal-zone fallback
CURRENT COST        very low, no subprocess
TARGET CHEAP SOURCE same /sys sources
PARSER/FIXTURE      Package id 0 / x86_pkg_temp millidegree conversion
SUBPROCESS REMAINS  no
CADENCE              FAST 10s
RECORDER             yes
PROBLEM/EVENT        CPU temperature MQTT threshold -> problem binary -> diagnostic event
```

## 3. CPU frequency

```text
CURRENT FIELD       cpu.frequency.*
CURRENT SOURCE      /sys/devices/system/cpu/cpufreq/policy*
CURRENT COST        low, no subprocess
TARGET CHEAP SOURCE same
PARSER/FIXTURE      cpuinfo_cur_freq preferred, scaling_cur_freq fallback; aggregate policy min/max/average
SUBPROCESS REMAINS  no
CADENCE              FAST 10s
RECORDER             average MHz yes; rich driver/governor metadata no
PROBLEM/EVENT        profile input only unless a future explicit problem is designed
```

## 4. CPU throttling

```text
CURRENT FIELD       cpu.throttling_active / counters
CURRENT SOURCE      /sys/devices/system/cpu/cpu*/thermal_throttle
CURRENT COST        low, no subprocess
TARGET CHEAP SOURCE same
PARSER/FIXTURE      monotonic package/core counter delta; reset/wrap must not synthesize a problem
SUBPROCESS REMAINS  no
CADENCE              FAST 10s
RECORDER             active state only if explicitly whitelisted; raw counters diagnostic
PROBLEM/EVENT        discrete throttling problem transition -> immediate event
```

## 5. RAM and Swap runtime

```text
CURRENT FIELD       memory usage, used/available, swap usage
CURRENT SOURCE      /proc/meminfo
CURRENT COST        very low, no subprocess
TARGET CHEAP SOURCE /proc/meminfo
PARSER/FIXTURE      MemTotal/MemAvailable/SwapTotal/SwapFree required; total > 0
SUBPROCESS REMAINS  no
CADENCE              FAST 10s
RECORDER             RAM % and Swap % yes
PROBLEM/EVENT        publication profile input; no default alert threshold currently frozen for RAM/Swap
```

## 6. Fan RPM

```text
CURRENT FIELD       fans.<id>.rpm
CURRENT SOURCE      /sys/class/hwmon/hwmon*/fan*_input
CURRENT COST        low, no subprocess
TARGET CHEAP SOURCE same
PARSER/FIXTURE      stable fan id from chip/device/index; invalid RPM -> unavailable
SUBPROCESS REMAINS  no
CADENCE              FAST 10s
RECORDER             yes
PROBLEM/EVENT        availability/data problem where applicable; no invented RPM alert threshold
```

## 7. Host load and uptime

```text
CURRENT FIELD       host load / uptime
CURRENT SOURCE      uptime from /proc/uptime; load not currently a dedicated runtime field
CURRENT COST        low
TARGET CHEAP SOURCE /proc/loadavg + /proc/uptime
PARSER/FIXTURE      loadavg 1/5/15 numeric fields; uptime finite non-negative
SUBPROCESS REMAINS  no
CADENCE              SLOW 1m
RECORDER             load only if selected by final explicit whitelist; uptime presentation/diagnostic
PROBLEM/EVENT        data-source failure only; no load alert invented by this refactor
```

## 8. Boot time

```text
CURRENT FIELD       host.boot_time
CURRENT SOURCE      /proc/stat `btime`
CURRENT COST        very low
TARGET CHEAP SOURCE /proc/stat `btime`
PARSER/FIXTURE      positive epoch -> timezone-aware timestamp
SUBPROCESS REMAINS  no
CADENCE              STATIC/startup
RECORDER             not continuous telemetry; used for boot notification/presentation
PROBLEM/EVENT        no threshold problem
```

## 9. Hardware/DMI identity

```text
CURRENT FIELD       Manufacturer, Model, MB
CURRENT SOURCE      /sys/class/dmi/id/*
CURRENT COST        very low
TARGET CHEAP SOURCE same
PARSER/FIXTURE      placeholder filtering already defined by host collector contract
SUBPROCESS REMAINS  no
CADENCE              STATIC
RECORDER             no; presentation only
PROBLEM/EVENT        source availability diagnostic only
```

## 10. CPU topology and RAM inventory

```text
CURRENT FIELD       CPU model/cores/threads; RAM type/form factor/slots/speed
CURRENT SOURCE      lscpu; dmidecode -t memory
CURRENT COST        subprocess, but currently hidden inside host collector
TARGET CHEAP SOURCE keep subprocess as rare STATIC inventory
PARSER/FIXTURE      existing lscpu + dmidecode fixtures, expanded for supported PVE hosts
SUBPROCESS REMAINS  yes, STATIC only
CADENCE              STATIC startup/.version-relevant refresh/Manual Refresh
RECORDER             no; presentation only
PROBLEM/EVENT        inventory/source diagnostic only
```

Do not replace these rare, understandable commands with speculative fragile parsing merely to reach zero subprocesses.

## 11. PVE/kernel version and primary IP

```text
CURRENT FIELD       Proxmox version, kernel, primary_ip
CURRENT SOURCE      pveversion -v; platform.release(); ip -j route get 1.1.1.1
CURRENT COST        rare subprocess for version/IP
TARGET CHEAP SOURCE kernel from uname/platform; PVE version via rare pveversion; primary route via rare bounded route lookup
PARSER/FIXTURE      pve-manager line parser; route JSON parser
SUBPROCESS REMAINS  yes, STATIC only for pveversion/IP lookup
CADENCE              STATIC
RECORDER             no; presentation only
PROBLEM/EVENT        source diagnostic only
```

`/etc/pve/.version` is a pmxcfs configuration revision object, not the installed `pve-manager` software version and must not be confused with it.

## 12. pmxcfs change detection

```text
CURRENT FIELD       none as a correctness mechanism
CURRENT SOURCE      topology polling/commands indirectly discover changes
CURRENT COST        unnecessarily high
TARGET CHEAP SOURCE /etc/pve/.version
PARSER/FIXTURE      JSON mapping; canonical parsed-object/fingerprint comparison
SUBPROCESS REMAINS  no
CADENCE              SLOW check every 1m; changed value triggers STATIC refresh
RECORDER             no
PROBLEM/EVENT        parser/read failure -> data-source problem transition
```

inotify/local events may trigger an earlier refresh but are optimization only.

## 13. VM/LXC inventory and type/node ownership

```text
CURRENT FIELD       VM/LXC ids, type, node membership
CURRENT SOURCE      pvesh /cluster/resources; fallback qm list + pct list
CURRENT COST        regular subprocess/API polling
TARGET CHEAP SOURCE /etc/pve/.vmlist
PARSER/FIXTURE      JSON {version, ids:{vmid:{node,type,version}}}; local-node filter; qemu/lxc only
SUBPROCESS REMAINS  no for normal inventory/runtime
CADENCE              STATIC, refreshed after .version change / Manual Refresh
RECORDER             no; topology/presentation
PROBLEM/EVENT        inventory/source failure diagnostic
```

The existing `pvesh -> qm/pct` fallback loop is removed.

## 14. VM/LXC runtime status

```text
CURRENT FIELD       guest.status and running counts
CURRENT SOURCE      pvesh /cluster/resources every guest poll; qm/pct fallback
CURRENT COST        high relative to required information
TARGET CHEAP SOURCE /etc/pve/.rrd `pve2.3-vm/<vmid>` + /etc/pve/.vmlist type map
PARSER/FIXTURE      PVE8 VM RRD fields; status index 2; ctime freshness; U -> None
SUBPROCESS REMAINS  no for normal runtime status
CADENCE              SLOW 1m
RECORDER             normally no; current-state/presentation, unless a specific state history is explicitly whitelisted
PROBLEM/EVENT        guest state transition immediate after SLOW detection; source failure diagnostic
```

RRD records older than the supported freshness bound are invalid rather than silently treated as current. Initial implementation uses a conservative 120-second freshness ceiling, matching PVE RRD heartbeat semantics while SLOW normally observes 10-second pvestatd data.

## 15. VM/LXC configuration and shutdown topology

```text
CURRENT FIELD       names/config, onboot, startup order/down, agent, hostpci, LXC DRI mappings
CURRENT SOURCE      direct /etc/pve config, with qm/pct config fallback on read failure
CURRENT COST        direct path cheap; fallback can become heavy
TARGET CHEAP SOURCE /etc/pve/qemu-server/*.conf and /etc/pve/lxc/*.conf only
PARSER/FIXTURE      direct config fixtures for startup/onboot/agent/hostpci/mp/dev mappings
SUBPROCESS REMAINS  no normal fallback
CADENCE              STATIC
RECORDER             no; topology/policy presentation
PROBLEM/EVENT        config source failure -> diagnostic/problem; no permanent CLI fallback
```

If a supported config file cannot be read, report the affected topology/config as unavailable instead of polling `qm config`/`pct config` forever.

## 16. PCI/GPU inventory and ownership

```text
CURRENT FIELD       PCI GPU model/driver and VM/LXC owner topology
CURRENT SOURCE      lspci -Dnn/-Dnnk each full/GPU scan + guest configs + /sys/class/drm
CURRENT COST        repeated subprocess despite mostly static topology
TARGET CHEAP SOURCE guest configs + /sys/class/drm; lspci only as rare STATIC inventory
PARSER/FIXTURE      existing lspci/hostpci/LXC DRI parsers; cached static catalog
SUBPROCESS REMAINS  yes, lspci STATIC only
CADENCE              STATIC
RECORDER             no; topology/presentation
PROBLEM/EVENT        topology/source diagnostic only
```

## 17. GPU temperature

```text
CURRENT FIELD       gpu.temperature_c
CURRENT SOURCE      /sys PCI-linked hwmon
CURRENT COST        low
TARGET CHEAP SOURCE same cached GPU inventory + /sys hwmon
PARSER/FIXTURE      canonical PCI BDF -> attached hwmon sensors; hottest valid sensor
SUBPROCESS REMAINS  no
CADENCE              SLOW 1m
RECORDER             yes
PROBLEM/EVENT        GPU temperature MQTT threshold -> problem -> event
```

## 18. GPU transcoding/utilization

```text
CURRENT FIELD       transcoding/video/render utilization
CURRENT SOURCE      host intel_gpu_top or VM QGA `qm guest exec ... intel_gpu_top`
CURRENT COST        necessary bounded subprocess; currently every 30s
TARGET CHEAP SOURCE same telemetry mechanism, but only for cached relevant GPUs/owners
PARSER/FIXTURE      existing intel_gpu_top JSON and QGA output fixtures
SUBPROCESS REMAINS  yes, necessary SLOW telemetry
CADENCE              SLOW 1m
RECORDER             transcoding load yes
PROBLEM/EVENT        publication profile input; GPU temperature problem separate
```

Do not run `pvesh`, `qm list`, `pct list`, `lspci`, or a separate QGA ping merely to decide whether to collect GPU utilization. Use cached STATIC ownership plus SLOW RRD guest state. QGA guest exec failure marks only that telemetry unavailable.

## 19. Storage configuration

```text
CURRENT FIELD       storage ids/types and dependency metadata
CURRENT SOURCE      implicitly from `pvesm status` output
CURRENT COST        subprocess and mixes static/runtime facts
TARGET CHEAP SOURCE /etc/pve/storage.cfg
PARSER/FIXTURE      PVE stanza `<type>: <id>` + indented options; preserve dependency-relevant fields
SUBPROCESS REMAINS  no
CADENCE              STATIC
RECORDER             no; presentation/diagnostics
PROBLEM/EVENT        config source failure diagnostic
```

This parser also provides the foundation for later NFS/CIFS/SMB provider/unmount diagnostics.

## 20. Storage percent used

```text
CURRENT FIELD       storage usage/total/used/free/status
CURRENT SOURCE      pvesm status every 60s
CURRENT COST        subprocess; may touch storage plugins/backends
TARGET CHEAP SOURCE /etc/pve/.rrd `pve2-storage/<node>/<storage-id>` + storage.cfg inventory
PARSER/FIXTURE      PVE8 fields ctime,total,used; free=max(total-used,0); percent only when total>0
SUBPROCESS REMAINS  no regular polling
CADENCE              SLOW 1m
RECORDER             percent used yes; rich capacities presentation only unless explicitly whitelisted
PROBLEM/EVENT        storage percent threshold -> per-storage problem -> event; missing/stale cache -> data problem
```

A storage absent from a fresh RRD snapshot is unavailable/inactive; it is not represented as zero usage.

## 21. Disk inventory / stable id

```text
CURRENT FIELD       local and passthrough physical disk identity
CURRENT SOURCE      smartctl --scan-open; guest QGA lsblk; full SMART payload
CURRENT COST        subprocess/QGA
TARGET CHEAP SOURCE persisted known inventory refreshed during HEALTH/STATIC-relevant topology changes
PARSER/FIXTURE      stable id from WWN/serial/path/model/size; existing missing-confirmation behavior retained
SUBPROCESS REMAINS  yes during HEALTH/on-demand inventory refresh
CADENCE              HEALTH + topology-triggered/on-demand refresh where explicitly required
RECORDER             no identity history; identity attrs kept compact
PROBLEM/EVENT        inventory/source failure diagnostic
```

## 22. Disk temperature

```text
CURRENT FIELD       disk.temperature_c
CURRENT SOURCE      full smartctl -a -j in SMART collector
CURRENT COST        full SMART work just to obtain a 1-minute temperature
TARGET CHEAP SOURCE known disk -> sysfs/hwmon first; bounded temperature-only SMART read only when sysfs has no temperature
PARSER/FIXTURE      block/NVMe-to-hwmon fixtures; SMART temperature subset fixtures; standby-safe handling
SUBPROCESS REMAINS  yes only as explicitly designed per-disk temperature fallback
CADENCE              SLOW 1m
RECORDER             yes
PROBLEM/EVENT        disk-type threshold -> per-disk temperature problem -> event
```

The SLOW temperature path must not perform full SMART health/counter processing. For ATA disks, the fallback must avoid waking a sleeping disk when the selected `smartctl` mode can report standby instead.

## 23. Full SMART health, wear and counters

```text
CURRENT FIELD       SMART health, wear, media/reallocation/pending/error counters, daily deltas
CURRENT SOURCE      smartctl --scan-open + smartctl -a -j; guest QGA smartctl where required
CURRENT COST        heavy and potentially multiplied by disk count/QGA
TARGET CHEAP SOURCE same authoritative SMART data, but only in HEALTH
PARSER/FIXTURE      existing SmartSnapshot parser + disk-type fixtures + per-disk fault isolation
SUBPROCESS REMAINS  yes, necessary
CADENCE              HEALTH 1h; sequential execution
RECORDER             wear yes; selected useful numeric counters as explicitly whitelisted; rich health details no
PROBLEM/EVENT        SMART/health transition -> immediate problem/event after HEALTH detects it
```

Manual Refresh may run HEALTH, but heavy per-disk operations execute sequentially.

## 24. QGA storage discovery for passed-through disks

```text
CURRENT FIELD       physical guest disk source path/model/serial/WWN
CURRENT SOURCE      QGA ping + `qm guest exec lsblk`
CURRENT COST        heavy if treated as regular topology polling
TARGET CHEAP SOURCE cached STATIC topology; QGA lsblk only when topology/relevant VM state requires discovery or Manual Refresh
PARSER/FIXTURE      existing lsblk JSON physical-disk filter
SUBPROCESS REMAINS  yes, rare/on-demand
CADENCE              STATIC/on-demand, not SLOW polling
RECORDER             no
PROBLEM/EVENT        unavailable QGA affects only dependent discovery/SMART source diagnostics
```

A separate periodic `qm agent <id> ping` is not required merely to maintain status. Attempt the specific bounded guest operation when needed and cache its result/state.

## 25. NUT UPS runtime

```text
CURRENT FIELD       UPS status/battery/runtime/load/voltage/frequency/test/beeper
CURRENT SOURCE      `upsc <ups>@<host>:<port>` subprocess, default config currently 5s
CURRENT COST        one small NUT client subprocess per poll
TARGET CHEAP SOURCE NUT via existing read path for first refactor; no speculative custom protocol client
PARSER/FIXTURE      complete standard token set; unknown tokens retained/tolerated; invalid numeric -> None
SUBPROCESS REMAINS  yes, necessary initial implementation
CADENCE              UPS fixed 10s
RECORDER             status mandatory + useful charge/runtime/load/voltage/power numeric telemetry
PROBLEM/EVENT        UPS discrete/problem transitions immediate; Trigger v2 uses current valid snapshot
```

Remove user/runtime control of UPS poll interval. A future direct NUT socket client is an optimization only if production evidence shows `upsc` cost matters.

## 26. NUT status/charger/power interpretation gaps

```text
CURRENT FIELD       status flags, charger state, real power
CURRENT SOURCE      ups.status CHRG/DISCHRG; nominal real power only
CURRENT COST        no extra acquisition required
TARGET CHEAP SOURCE same `upsc` snapshot
PARSER/FIXTURE      OL OB LB HB RB CHRG DISCHRG BYPASS CAL OFF OVER TRIM BOOST FSD ALARM + unknown tokens;
                    battery.charger.status preferred; CHRG/DISCHRG fallback;
                    ups.realpower preferred, nominal*load/100 fallback
SUBPROCESS REMAINS  no additional process beyond the one UPS read
CADENCE              UPS 10s
RECORDER             status + useful numeric telemetry
PROBLEM/EVENT        canonical UPS problem/event mapping
```

## 27. NUT capabilities and battery-test control

```text
CURRENT FIELD       command capabilities / Quick Deep Stop / beeper
CURRENT SOURCE      upscmd list/actions
CURRENT COST        subprocess/network action
TARGET CHEAP SOURCE retain capability read at startup/Manual Refresh; explicit actions only
PARSER/FIXTURE      command-list normalization; strict allow-list
SUBPROCESS REMAINS  yes, rare/action
CADENCE              STATIC/on-demand/action
RECORDER             controls/history presentation not broad Recorder
PROBLEM/EVENT        action/config result events where designed; no arbitrary command path
```

## 28. Shutdown history

```text
CURRENT FIELD       clean/unclean, reason, per-guest duration/result, total guest interval, host timing
CURRENT SOURCE      previous-boot journald parsing + app state store
CURRENT COST        potentially large journal subprocess at startup only
TARGET CHEAP SOURCE retain bounded startup/boot-transition history extraction; no periodic journal scan
PARSER/FIXTURE      existing timestamp/task/clean markers; keep reason separate from clean fact
SUBPROCESS REMAINS  yes, startup/boot evidence only
CADENCE              STATIC/startup after a new boot
RECORDER             rich history entity no; selected presentation/current fields only if explicitly required
PROBLEM/EVENT        readiness/budget evidence; unclean shutdown diagnostic
```

## 29. Shutdown budget

```text
CURRENT FIELD       guest_shutdown_budget_seconds
CURRENT SOURCE      direct guest configs + qm/pct running lists + nproc + NUT policy facts
CURRENT COST        policy read can spawn qm/pct/upsc/nproc
TARGET CHEAP SOURCE STATIC guest configs + SLOW .rrd runtime membership + cheap CPU count + persisted comparable shutdown history + NUT config/runtime facts
PARSER/FIXTURE      configured ceiling by PVE group/concurrency semantics; comparable-history fingerprint; host-tail evidence
SUBPROCESS REMAINS  only for NUT facts that have no cheap local config/runtime equivalent; no qm/pct list
CADENCE              derived on relevant STATIC/SLOW/history/policy changes + Manual Refresh
RECORDER             derived policy/budget presentation not continuous Recorder telemetry
PROBLEM/EVENT        unavailable mandatory budget component -> readiness/problem; policy apply config_changed event
```

`max_workers` comes from `/etc/pve/datacenter.cfg` when configured. When PVE uses its default worker count, derive the effective host CPU count from the already-known local CPU topology instead of spawning `nproc` each recalculation.

History may increase but never reduce the current configured guest ceiling.

## 30. UPS Trigger Policy v2 decision inputs

```text
CURRENT FIELD       old on_battery_delay policy; no approved Trigger A/B runtime engine yet
CURRENT SOURCE      old policy state/upssched model
CURRENT COST        not applicable to final contract
TARGET CHEAP SOURCE current 10s UpsSnapshot + derived cached shutdown budget + active persisted policy
PARSER/FIXTURE      Trigger A: OB && valid charge <= threshold;
                    Trigger B: OB && valid runtime <= budget+reserve;
                    native LB independent;
                    invalid/missing never zero
SUBPROCESS REMAINS  no additional acquisition beyond UPS read
CADENCE              every valid UPS 10s snapshot / immediate active-policy recompute
RECORDER             policy presentation no; underlying UPS telemetry according to whitelist
PROBLEM/EVENT        local PVE/NUT shutdown commitment; diagnostic/config events; HA never commits shutdown
```

---

## Recorder outcome

The source refactor does not use source type to decide Recorder. Recorder remains an explicit semantic whitelist.

Recorded PVE numeric history includes at least:

```text
CPU usage
a CPU temperature
CPU frequency
RAM usage
Swap usage
fan RPM
disk temperature
disk wear
storage percent used
GPU temperature
GPU transcoding load
```

UPS explicitly includes `sensor.dh_app_pve_ups_status` plus useful numeric charge/runtime/load/voltage/power telemetry selected by the final package contract.

Presentation, topology, rich SMART detail, publication diagnostics and native MQTT Event entities are not Recorder.

---

## Current heavy paths to remove from regular polling

The implementation must eliminate these normal-loop behaviors:

```text
pvesh get /cluster/resources every guest-status poll
pvesh failure -> qm list + pct list every poll
pvesm status every SLOW cycle
qm/pct config fallback every config read failure
lspci every GPU SLOW collection
QGA ping every minute merely to maintain topology state
QGA lsblk as regular polling
full smartctl -a just to obtain disk temperature
runtime-configurable FAST/SMART/UPS poll intervals
load-triggered collection acceleration
```

The following subprocess families remain by design, but only at bounded cadence/scope:

```text
STATIC: lscpu, dmidecode, lspci, pveversion, bounded primary-route lookup
SLOW: intel_gpu_top; QGA intel_gpu_top where passthrough requires it; temperature-only smartctl fallback where sysfs cannot provide disk temperature
HEALTH: smartctl full health; guest QGA smartctl for physical disks owned inside a VM
UPS: one upsc read every 10s
ON-DEMAND/ACTION: upscmd capability/control, battery tests, beeper, explicit policy service/config actions
STARTUP: previous-boot journal extraction for shutdown history
```

---

## Required new reader boundaries

Implementation should create focused readers rather than expand the current monolithic `ProductionCollectors`:

```text
PveVersionReader
  /etc/pve/.version -> change fingerprint

PveVmListReader
  /etc/pve/.vmlist -> VMID/type/node/version inventory

PveRrdReader
  /etc/pve/.rrd -> node/guest/storage runtime records with freshness validation

PveGuestConfigReader
  /etc/pve/qemu-server/*.conf and /etc/pve/lxc/*.conf -> static config/topology/shutdown fields

PveStorageConfigReader
  /etc/pve/storage.cfg -> storage inventory/dependency metadata

DiskTemperatureReader
  persisted disk inventory -> sysfs/hwmon first -> bounded SMART temperature fallback
```

Exact Python class/function naming may be reduced during implementation if smaller pure functions make the code clearer, but these responsibilities must remain isolated and fixture-testable.

---

## Implementation gate

The source audit is complete when the implementation obeys all of the following:

```text
FAST runtime has zero subprocess acquisition
VM/LXC normal runtime status has zero subprocess acquisition
storage normal runtime usage has zero subprocess acquisition
STATIC pmxcfs config reads do not fall back into permanent CLI polling
full SMART exists only in HEALTH/Manual Refresh
GPU subprocess work uses cached STATIC ownership and SLOW state
UPS collection is fixed at 10s and performs no additional policy polling per sample
.version is checked every SLOW cycle
invalid/missing/stale cache values never become zero
all PVE 8 internal cache parsers have fixtures
```

This audit freezes sources, not implementation details. If production evidence proves a target PVE 8 file/cache field unavailable or semantically different on the deployment host, stop and revise the source contract rather than silently adding a heavy fallback loop.
