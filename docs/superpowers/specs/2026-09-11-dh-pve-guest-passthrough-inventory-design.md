# DH PVE App — Guest / Passthrough Inventory Design

**Date:** 2026-09-11  
**Status:** Proposed for implementation  
**Application:** `dh_pve_app`  
**Scope:** VM/LXC inventory, passthrough topology, guest-derived SMART, guest-aware GPU telemetry

## 1. Purpose

Extend `dh_pve_app` with a shared guest/topology layer so Proxmox VM/LXC state, PCI passthrough ownership, guest-derived SMART data, and existing guest-derived GPU telemetry use one consistent source of truth.

The current Python implementation already discovers GPU ownership from Proxmox configuration and can execute `intel_gpu_top` inside a running VM through QEMU Guest Agent. The missing parity is storage passthrough: a physical disk behind a PCI SATA controller passed to a VM is intentionally invisible to host `lsblk`/`smartctl` and therefore must be collected from inside that VM.

The initial live reference case is:

```text
PVE
├─ local NVMe
│  └─ Samsung SSD 990 EVO 1TB → host smartctl
├─ VM 700 TrueNAS
│  └─ hostpci0 0000:00:17.0 SATA controller
│      └─ QEMU Guest Agent → Samsung SSD 850 EVO 1TB SMART
└─ VM 501 plex-vm
   └─ Intel UHD Graphics passthrough
       └─ QEMU Guest Agent → intel_gpu_top transcoding telemetry
```

The feature must be autonomous. A normal installation must not require manual lists such as `passthrough_vms = 700` or separate `disk_vms` / `gpu_vms` configuration.

## 2. Architectural principle

Separate **topology discovery** from **runtime status polling**.

Topology changes rarely and should not be rescanned on every fast polling cycle. Guest status changes frequently and should remain lightweight to monitor.

```text
START dh_pve_app
    ↓
Full topology discovery
    ├─ VM inventory
    ├─ LXC inventory
    ├─ qm/pct config
    ├─ hostpci / device passthrough mapping
    ├─ guest-agent capability
    └─ collector source map

RUN
    ├─ VM/LXC state polling
    ├─ CPU/RAM/etc polling
    ├─ SMART using cached source map
    └─ GPU using cached source map

VM/LXC stopped → running
    ↓
Targeted topology rescan for that guest

Manual Refresh
    ↓
Full topology discovery again
```

No Home Assistant restart is required. No `dh_pve_app` restart is required after a normal guest restart. If passthrough configuration changes, the new mapping becomes active when the affected guest starts and the app detects the transition.

## 3. Guest inventory

Add a dedicated guest inventory subsystem covering both QEMU VMs and LXC containers.

For each guest, normalize at least:

```text
kind          vm | lxc
guest_id      numeric VMID/CTID
name          Proxmox guest name
status        running | paused | stopped | unknown
agent_enabled true | false | unknown       # VM only where applicable
hostpci       normalized passthrough list
```

The runtime view is read-only in this phase. The application must not expose Start, Stop, Shutdown, Reboot, Pause, Resume, or Reset actions.

Status monitoring must remain lightweight. It may use `qm list` / `pct list` and targeted status reads where required for reliable normalization.

## 4. Home Assistant guest entities

Expose one state entity per VM/LXC because guest status is multi-state rather than boolean.

Recommended entity pattern:

```text
sensor.dh_pve_vm_110_status
sensor.dh_pve_vm_501_status
sensor.dh_pve_vm_700_status
sensor.dh_pve_lxc_500_status
```

State:

```text
running
paused
stopped
unknown
```

Attributes should remain compact and recorder-safe:

```text
proxmox_integration: dh_pve_app
proxmox_section: guests
proxmox_subject: vm | lxc
proxmox_metric: status
proxmox_object_id: vm_700 | lxc_500
proxmox_display_name: TrueNAS
guest_id: 700
guest_kind: vm
passthrough_count: N
qemu_agent: available | unavailable | disabled | unknown
proxmox_sort_key: ...
```

Expose summary entities:

```text
sensor.dh_pve_vms
sensor.dh_pve_lxcs
```

The state should be the number of running guests. Attributes contain small aggregate counts:

```text
total
running
paused
stopped
unknown
```

No large guest inventory arrays should be duplicated in summary entity attributes.

## 5. Passthrough topology inventory

At full topology discovery, inspect Proxmox guest configuration and build an internal mapping of host devices to owners.

At minimum support QEMU `hostpciN` assignments. Preserve enough raw information to identify:

```text
owner kind
owner guest ID
owner guest name
hostpci key
PCI address / configured device expression
runtime guest status
QEMU Guest Agent capability
```

The mapping is shared infrastructure for collectors; GPU and SMART must not independently re-parse guest configuration on every poll.

A topology scan occurs:

1. at application startup;
2. on manual `button.dh_pve_refresh`;
3. on `stopped/paused → running` transition for the affected VM/LXC where relevant;
4. optionally on an explicit internal recovery event if cached topology is invalid.

Normal fast polling must not continuously reread all `qm config` / `pct config` files or execute guest inventory commands.

## 6. Guest-derived physical disk discovery

Host SMART remains authoritative for locally visible physical disks.

For a running VM that owns a passthrough PCI storage controller or another supported physical-storage passthrough, the SMART collector may use QEMU Guest Agent to inspect physical disks inside the guest.

The guest probe should conceptually perform:

```text
qm guest exec <vmid> -- /bin/sh -c <guest inventory command>
```

Guest inventory must distinguish virtual system disks from physical disks. In the live TrueNAS case:

```text
/dev/sda  QEMU HARDDISK             → virtual, exclude
/dev/sdb  Samsung SSD 850 EVO 1TB   → physical, include
```

Filtering must be conservative. Known Proxmox/QEMU virtual-disk signatures such as `QEMU HARDDISK` / `drive-*` may be excluded, but a disk should not be silently discarded merely because one optional transport field is missing.

For included guest physical disks, read SMART JSON inside the guest using the same normalization pipeline as local disks. The resulting `SmartSnapshot`, disk health evaluation, daily statistics, counters, and MQTT Discovery semantics must be identical to locally collected disks.

## 7. Stable disk identity across host and guest sources

A physical disk must retain the same stable identity regardless of whether it is currently read from the host or through a guest.

Identity priority remains:

```text
WWN → serial → stable fallback
```

The source path is not part of the preferred identity.

For the reference TrueNAS disk the stable object should therefore be based on:

```text
WWN   0x5002538d41046527
serial S2PWNX0H603177N
model  Samsung SSD 850 EVO 1TB
```

Guest source metadata may be added as compact attributes:

```text
source_type: guest
source_guest_id: 700
source_guest_name: TrueNAS
source_device_path: /dev/sdb
passthrough_hostpci: hostpci0
```

This metadata must not change the entity unique ID when the same physical disk moves between equivalent collection paths.

## 8. SMART failure isolation

Guest-derived SMART must preserve existing fault-isolation behavior.

Examples:

```text
VM 700 stopped
→ guest-derived Samsung 850 SMART becomes unavailable
→ local Samsung 990 SMART remains valid

QEMU Guest Agent unavailable
→ only guest-derived data becomes unavailable
→ guest status still remains visible

smartctl fails for /dev/sdb inside VM 700
→ only that physical disk becomes unavailable
→ topology and unrelated collectors remain valid
```

A temporary VM stop or guest-agent failure must not immediately delete the disk Discovery entity. Existing conservative missing-object confirmation remains applicable, but a known guest source that is merely offline must be treated as unavailable rather than physically removed.

## 9. QEMU Guest Agent semantics

Guest Agent is a capability, not a requirement for a guest to exist in inventory.

For VMs:

```text
agent disabled         → VM status still monitored; guest probes unavailable
agent enabled/offline  → VM status still monitored; guest-derived collectors unavailable
agent enabled/working  → guest probes allowed
```

The app must not spam guest commands against stopped VMs.

Guest-agent probe failures should be logged concisely and rate-limited through normal collector scheduling/state-change behavior rather than producing repetitive log noise every second.

## 10. GPU integration

Existing GPU behavior must be preserved while moving topology ownership to the shared layer.

The shared topology map should provide:

```text
PCI address
owner VM/LXC
owner ID
owner name
connection type
runtime status
```

The GPU collector remains responsible for GPU-specific telemetry such as temperature and Intel transcoding load.

For the reference Plex VM:

```text
Intel UHD → VM 501 plex-vm → running → QEMU Guest Agent → intel_gpu_top
```

This refactor must not regress existing `sensor.dh_pve_gpu_*_owner` or transcoding entities.

## 11. Runtime polling and topology refresh

Introduce a lightweight guest-status task, independent of full topology discovery.

Recommended initial cadence:

```text
VM/LXC status: 10–15 s
full topology scan: startup/manual refresh only
```

A guest status change is a discrete event and should publish immediately.

When the runtime detects a transition to `running`, it compares the current guest identity/config fingerprint with the cached topology. If necessary it rescans that guest and refreshes dependent collector source maps.

A transition to `stopped` or `paused` immediately marks guest-derived telemetry unavailable where live execution is required, but does not delete the underlying topology relationship.

## 12. Persistence

Persist the last valid topology under `/var/lib/dh_pve_app/` in a dedicated or clearly separated state file.

Persisted topology is a recovery cache only. On startup, current Proxmox configuration remains authoritative and must refresh the cache.

Corrupt cached topology must not prevent service startup. Log a clear error and rebuild from current Proxmox state.

## 13. Dynamic Discovery behavior

Guest entities and guest-derived disks use the existing dynamic Discovery mechanism.

Inventory changes that add/remove VM/LXC entities or physical disks must trigger Discovery republish.

Stable objects must not receive new entity IDs merely because ordering changed.

Recommended semantic sort groups:

```text
700_xxx  guests
400_xxx  physical disks   # existing disk group retained
500_xxx  graphics         # existing GPU group retained
```

Exact numeric prefixes may be adjusted during implementation as long as ordering remains deterministic and compatible with `auto-entities`.

## 14. Dashboard contract

The production dashboard remains a four-column/section layout.

Add a compact read-only guest list in the hardware/system area using semantic attributes rather than hard-coded site guest IDs.

Preferred presentation:

```text
VMs  2 / 3 running
110 · HAOS      · stopped
501 · plex-vm   · running
700 · TrueNAS   · running

LXCs 1 / 1 running
500 · recorder  · running
```

Use status color only as presentation. No control actions are exposed.

Physical disk cards remain dynamically generated. Once guest SMART is implemented, Samsung SSD 850 EVO must appear automatically next to Samsung SSD 990 EVO without dashboard-specific knowledge of VM 700.

## 15. Out of scope

This phase explicitly excludes:

```text
VM/LXC start/stop/restart controls
HA automations that manage guest lifecycle
Proxmox API tokens / remote cluster monitoring
continuous full topology scans
manual site-specific passthrough VM lists as the primary mechanism
UPS/NUT support
notification package redesign
```

## 16. Acceptance criteria

Implementation is accepted when all of the following are true:

1. VM and LXC inventory is automatically discovered and exposed read-only in HA.
2. `running / paused / stopped / unknown` guest states update without restarting `dh_pve_app` or Home Assistant.
3. Full passthrough topology is built at startup and manual refresh, not every fast poll.
4. A stopped→running transition can refresh the affected guest topology automatically.
5. VM 700 is detected as owner of PCI `0000:00:17.0`.
6. QEMU Guest Agent inventory for VM 700 identifies Samsung SSD 850 EVO 1TB and excludes the virtual `QEMU HARDDISK` system disk.
7. Samsung SSD 850 EVO is processed by the same SMART/health/daily-stat pipeline as local Samsung SSD 990 EVO.
8. Stable disk identity uses WWN/serial and does not depend on guest `/dev/sdX` path.
9. Stopping VM 700 makes only guest-derived SMART telemetry unavailable; it does not remove the disk immediately or break local SMART.
10. Existing VM 501 Intel GPU owner/transcoding monitoring continues to work.
11. Dashboard can list VM/LXC states dynamically and shows both physical Samsung disks when available.
12. No VM/LXC control actions are published.
13. Existing Phase-1 tests remain green and new guest/topology/guest-SMART cases have regression coverage.
