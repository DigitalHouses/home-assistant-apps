# DH PVE App

`dh_pve_app` is a native DigitalHouses Linux agent for Proxmox VE. It collects host, CPU, memory, storage, physical-disk/SMART, GPU/transcoding, fan, VM/LXC, and passthrough topology telemetry and publishes normalized Home Assistant entities through MQTT Discovery.

Phase 1 intentionally runs alongside the legacy Bash Proxmox-to-MQTT script. The new app uses its own MQTT namespace and Home Assistant entity IDs, so both implementations can be compared before cutover. Version `0.2.0-alpha` adds optional read-only UPS monitoring through NUT for validation.

## Public identity

- Home Assistant MQTT device: `DH PVE`
- Optional UPS MQTT device: `DH UPS`
- MQTT base namespace: `DigitalHouses/Global/dh_pve_app/<instance>`
- PVE entity prefix: `dh_pve_`
- UPS entity prefix: `dh_ups_`
- Service: `dh_pve_app.service`
- Install directory: `/opt/digitalhouses/dh_pve_app/`
- Config: `/etc/dh_pve_app/dh_pve_app.conf`
- Persistent state: `/var/lib/dh_pve_app/`

The default instance ID is derived from `/etc/machine-id`, so multiple Proxmox hosts do not collide.

## Runtime model

Collectors poll Proxmox/Linux locally. MQTT state is published only for meaningful metric deltas, discrete events, inventory changes, collector failure/recovery, reconnect restoration, or a manual refresh. There is no periodic state heartbeat; process/MQTT liveness uses retained availability plus MQTT LWT.

A failure in one collector does not make unrelated subsystems unavailable. SMART reads are isolated per physical disk, and a disk is removed from inventory only after three consecutive authoritative scans confirm that it is absent.

Runtime polling/publish parameters can be adjusted from Home Assistant within application-defined hard limits. SMART/disk-health policy is version-controlled in the app and cannot be changed from Home Assistant.

Expensive Proxmox helper processes are deliberately kept out of the fast loop. Cheap CPU/memory/fan sampling may run at the fast interval, while VM/LXC status and guest GPU telemetry use a 30-second cadence. New installations use a 60-second SMART polling default.

## UPS / NUT monitoring alpha

UPS monitoring is optional and strictly read-only in `0.2.0-alpha`. NUT remains the hardware authority: the app never accesses the UPS over USB and never configures NUT. The first backend reads one UPS with `upsc` from an existing NUT server, normally on the same Proxmox host.

Enable it with an optional config section:

```ini
[ups]
enabled = true
name = ups
host = 127.0.0.1
port = 3493
poll_interval_seconds = 5
command_timeout_seconds = 3
```

Existing configurations without `[ups]` remain valid and keep UPS monitoring disabled.

When enabled, the same process and MQTT client publish a separate Home Assistant device named `DH UPS`. Its MQTT namespace is subordinate to the PVE app instance:

```text
DigitalHouses/Global/dh_pve_app/<instance>/ups/state
DigitalHouses/Global/dh_pve_app/<instance>/ups/availability
DigitalHouses/Global/dh_pve_app/<instance>/ups/refresh
homeassistant/device/dh_ups_<instance>/config
```

Discovery is capability-driven. Only variables actually reported by NUT are exposed. Supported normalized facts include UPS status, battery charge/runtime/voltage, load, input/output voltage, nominal real power, estimated real power, warning/low thresholds, test result and beeper status. NUT status tokens such as `OL`, `OB` and `LB` are parsed in Python into understandable states and binary sensors; the raw NUT status is retained as an attribute.

UPS telemetry is polled independently from PVE telemetry. Discrete power-state changes publish immediately; numeric state uses version-controlled deltas (1 percentage point, 1 V, 60 s runtime). A NUT read failure makes only `DH UPS` unavailable and does not interrupt `DH PVE` monitoring.

This alpha contains **no** UPS power-control path: it does not enable or control `upsmon`, FSD, Proxmox shutdown, guest shutdown, battery tests, beeper control or outlet control. Shutdown coordination is intentionally deferred until physical testing on a locally accessible site.

## Guest and passthrough topology

The app discovers Proxmox guests automatically; no site-specific `disk_vms`, `gpu_vms`, or passthrough VM lists are required.

Topology behavior is deliberately split into a heavy and a lightweight path:

- A full topology scan runs at app startup and on `button.dh_pve_refresh`.
- VM/LXC status is polled independently every 30 seconds through one `/cluster/resources` query instead of separate `qm list` and `pct list` processes.
- Guest configuration is normally read directly from pmxcfs under `/etc/pve/qemu-server` and `/etc/pve/lxc`; `qm config` / `pct config` are fallback paths only.
- A guest transition from non-running to `running` triggers a targeted rescan of that guest rather than a full topology rebuild.
- VM `hostpciN` PCI passthrough is detected and cached.
- Existing LXC shared `/dev/dri` GPU ownership remains supported.
- VM/LXC Home Assistant entities are read-only status/diagnostic entities; the app does not expose guest start/stop/reboot controls.

For storage-class PCI passthrough, a running VM with a working QEMU Guest Agent (QGA) is inspected with `lsblk`. Eligible physical disks are then queried through guest `smartctl -a -j` and fed into the same stable-ID, SMART parser, health engine, daily statistics, and MQTT Discovery pipeline as host-local disks. A stopped guest or unavailable QGA marks the guest-derived disk telemetry unavailable without immediately deleting the disk from inventory.

GPU ownership also uses the shared topology cache. Guest-side Intel GPU telemetry continues to use QGA when the GPU is assigned to a VM, but the expensive guest telemetry command is scheduled at 30 seconds rather than in the fast CPU/memory loop.

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

A manual PVE refresh runs the full topology scan first, then all enabled PVE collectors, and forces a state publication. `last_refresh` advances only after a successful full refresh.

When UPS monitoring is enabled, it additionally exposes:

- `button.dh_ups_refresh`
- `sensor.dh_ups_last_refresh`

UPS refresh is independent and advances its timestamp only after a successful NUT read.

## Dashboard

A production Lovelace view is provided at:

```text
dh_pve_app/examples/dh_pve_dashboard.yaml
```

It requires the HACS cards **Mushroom**, **auto-entities**, **mini-graph-card**, and **Entity Progress Card**.

The dashboard uses Python-normalized values directly. Storage progress uses `usage_percent` plus `used_gib / total_gib`, disk health remains the Python-produced `HEALTHY/WARNING/CRITICAL` state, and Home Assistant does not calculate infrastructure health.

UPS dashboard and notifications are deferred until live alpha telemetry has been validated on real hardware.

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

The installer does not install/configure NUT, edit `/etc/nut/*`, or enable `nut-monitor`. UPS support simply reports unavailable if the configured read-only `upsc` backend cannot be reached.

The service intentionally runs as root because SMART, `/etc/pve` guest configuration and passthrough inspection require host-level read access.

## Validation

The installer does **not** disable, edit, or remove the legacy `digitalhouses-proxmox-mqtt.sh` cron job. Compare the new `DH PVE` device against legacy entities before any cutover.

Basic service diagnostics:

```bash
systemctl status dh_pve_app --no-pager
journalctl -u dh_pve_app -n 100 --no-pager
```

For UPS alpha validation, also verify the NUT source independently:

```bash
upsc ups@127.0.0.1:3493
```

Expected alpha behavior is a separate `DH UPS` MQTT device, capability-driven entities matching the actual UPS, and uninterrupted `DH PVE` operation if NUT becomes unavailable.

## Status

Version `0.2.0-alpha` is a validation build for read-only NUT-backed UPS telemetry. Shutdown/FSD policy, LAN NUT clients, notifications and UPS dashboard work remain separate later phases.
