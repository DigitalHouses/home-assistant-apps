# DH PVE App

`dh_pve_app` is a native DigitalHouses Linux agent for Proxmox VE. It collects host, CPU, memory, storage, physical-disk/SMART, GPU/transcoding, fan, VM/LXC, and passthrough topology telemetry and publishes normalized Home Assistant entities through MQTT Discovery.

Phase 1 intentionally runs alongside the legacy Bash Proxmox-to-MQTT script. The new app uses its own MQTT namespace and Home Assistant entity IDs, so both implementations can be compared before cutover.

## Public identity

- Home Assistant MQTT device: `DH PVE`
- MQTT base namespace: `DigitalHouses/Global/dh_pve_app/<instance>`
- Home Assistant entity prefix: `dh_pve_`
- Service: `dh_pve_app.service`
- Install directory: `/opt/digitalhouses/dh_pve_app/`
- Config: `/etc/dh_pve_app/dh_pve_app.conf`
- Persistent state: `/var/lib/dh_pve_app/`

The default instance ID is derived from `/etc/machine-id`, so multiple Proxmox hosts do not collide.

## Runtime model

Collectors poll Proxmox/Linux locally. MQTT state is published only for meaningful metric deltas, discrete events, inventory changes, collector failure/recovery, reconnect restoration, or a manual refresh. There is no periodic state heartbeat; process/MQTT liveness uses retained availability plus MQTT LWT.

A failure in one collector does not make unrelated subsystems unavailable. SMART reads are isolated per physical disk, and a disk is removed from inventory only after three consecutive authoritative scans confirm that it is absent.

Runtime polling/publish parameters can be adjusted from Home Assistant within application-defined hard limits. SMART/disk-health policy is version-controlled in the app and cannot be changed from Home Assistant.

## Guest and passthrough topology

The app discovers Proxmox guests automatically; no site-specific `disk_vms`, `gpu_vms`, or passthrough VM lists are required.

Topology behavior is deliberately split into a heavy and a lightweight path:

- A full topology scan runs at app startup and on `button.dh_pve_refresh`.
- VM/LXC status is polled independently with a lightweight 10-second guest-state collector.
- A guest transition from non-running to `running` triggers a targeted rescan of that guest rather than a full topology rebuild.
- VM `hostpciN` PCI passthrough is detected and cached.
- Existing LXC shared `/dev/dri` GPU ownership remains supported.
- VM/LXC Home Assistant entities are read-only status/diagnostic entities; the app does not expose guest start/stop/reboot controls.

For storage-class PCI passthrough, a running VM with a working QEMU Guest Agent (QGA) is inspected with `lsblk`. Eligible physical disks are then queried through guest `smartctl -a -j` and fed into the same stable-ID, SMART parser, health engine, daily statistics, and MQTT Discovery pipeline as host-local disks. A stopped guest or unavailable QGA marks the guest-derived disk telemetry unavailable without immediately deleting the disk from inventory.

GPU ownership also uses the shared topology cache, so fast GPU polling does not repeatedly reparse every Proxmox guest configuration. Guest-side Intel GPU telemetry continues to use QGA when the GPU is assigned to a VM.

## Storage semantics

Storage entities use **used / total** semantics. Home Assistant receives ready-to-display `usage_percent`, `used_gib`, and `total_gib`; it does not need templates to calculate infrastructure values. `available_gib` may exist in the internal collector payload but is not the primary storage UI contract.

## Disk health

Disk health is computed by the Python agent and exposed as exactly:

- `HEALTHY`
- `WARNING`
- `CRITICAL`

The health engine evaluates SMART overall status, NVMe critical warnings, wear, media/reallocated/pending/uncorrectable errors, unsafe-shutdown growth, temperature, and counter growth. Daily statistics include maximum temperature and sparse lifetime counters for Recorder-friendly history.

Home Assistant templates may format or filter these ready facts, but must not recompute infrastructure health or disk thresholds.

## Manual refresh

Home Assistant exposes:

- `button.dh_pve_refresh`
- `sensor.dh_pve_last_refresh`

A manual refresh runs the full topology scan first, then all enabled collectors, and forces a state publication. `last_refresh` advances only after a successful full refresh.

## Dashboard

A production Lovelace view is provided at:

```text
dh_pve_app/examples/dh_pve_dashboard.yaml
```

It requires the HACS cards **Mushroom**, **auto-entities**, **mini-graph-card**, and **Entity Progress Card**.

The production view is intentionally built as four continuous desktop columns rather than many independent Sections:

1. Host → Proxmox state → performance → system → disk diagnostics.
2. Physical disks → Proxmox storage → monitoring/runtime settings.
3. CPU/RAM/Swap → CPU/throttling → cooling → graphics → VM/LXC → collector diagnostics.
4. History.

Dynamic storage, physical disks, GPU, fans, VM/LXC, runtime settings, and collector diagnostics are selected through the `proxmox_*` semantic attributes emitted by MQTT Discovery rather than hard-coded hardware entity IDs. Guest-derived physical disks therefore appear in the same disk list automatically.

The dashboard uses Python-normalized values directly. Storage progress uses `usage_percent` plus `used_gib / total_gib`, disk health remains the Python-produced `HEALTHY/WARNING/CRITICAL` state, and Home Assistant does not calculate infrastructure health.

## Installation

Run on the Proxmox host as `root`:

```bash
curl -fsSL https://raw.githubusercontent.com/DigitalHouses/home-assistant-apps/main/dh_pve_app/install.sh | bash
```

On first installation the installer asks only for MQTT host, port, username, and password. Host identity is detected automatically. Existing valid configuration is preserved on upgrades.

If configuration validation fails, the installer does not overwrite the file and points to:

```bash
nano /etc/dh_pve_app/dh_pve_app.conf
```

The service intentionally runs as root because SMART, `/etc/pve` guest configuration, passthrough inspection, and future NUT diagnostics require host-level read access.

## Phase 1 validation

The installer does **not** disable, edit, or remove the legacy `digitalhouses-proxmox-mqtt.sh` cron job. After installation, compare the new `DH PVE` device against the legacy entities before any cutover.

Basic service diagnostics:

```bash
systemctl status dh_pve_app --no-pager
journalctl -u dh_pve_app -n 100 --no-pager
```

Guest/topology checks on Proxmox:

```bash
qm list
pct list
qm config 700 | grep -E '^(name|agent|hostpci)'
qm config 501 | grep -E '^(name|agent|hostpci)'
qm agent 700 ping
qm agent 501 ping
```

For the current validation host, acceptance is:

- `sensor.dh_pve_vm_700_status` shows the TrueNAS VM state.
- `sensor.dh_pve_vm_501_status` shows the Plex VM state.
- `sensor.dh_pve_vms` / `sensor.dh_pve_lxcs` expose running counts and total/paused/stopped/unknown attributes.
- VM 700 storage passthrough is detected from `hostpci` and the Samsung SSD 850 EVO 1TB appears alongside the host-local Samsung SSD 990 EVO 1TB when QGA/SMART are available.
- The Samsung SSD 850 EVO reports WWN `0x5002538d41046527`, serial `S2PWNX0H603177N`, and Python-produced disk health.
- VM 501 keeps Intel GPU ownership and transcoding telemetry through the shared topology cache.
- Pressing `button.dh_pve_refresh` rebuilds topology and updates `sensor.dh_pve_last_refresh`.
- `examples/dh_pve_dashboard.yaml` renders as four continuous columns on a desktop-width view.

Do not retire the legacy Bash agent until side-by-side parity is accepted on the live host.

## Status

Version `0.1.0` is the initial Phase 1 implementation. UPS/NUT support is reserved for Phase 2 and will use a separate `DH UPS` MQTT device.
