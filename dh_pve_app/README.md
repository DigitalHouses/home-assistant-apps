# DH PVE App

`dh_pve_app` is a native DigitalHouses Linux agent for Proxmox VE. It collects host, CPU, memory, storage, physical-disk/SMART, GPU/transcoding, fan, VM/LXC, passthrough topology, and optional UPS telemetry and publishes normalized Home Assistant entities through MQTT Discovery.

Phase 1 intentionally runs alongside the legacy Bash Proxmox-to-MQTT script. Version `0.2.0-alpha` adds optional read-only UPS monitoring through NUT for validation on real hardware.

## Public identity

- Home Assistant MQTT device: `DH PVE`
- Optional UPS MQTT device: `DH PVE UPS`
- MQTT base namespace: `DigitalHouses/Global/dh_pve_app/<instance>`
- PVE entity prefix: `dh_pve_`
- UPS entity prefix: `dh_pve_ups_`
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

UPS monitoring is optional and strictly read-only in `0.2.0-alpha`. NUT remains the hardware authority: the app never accesses the UPS over USB and never configures NUT. The backend reads UPS data from an existing NUT server with `upsc`, normally on the same Proxmox host.

The default NUT endpoint is:

```text
127.0.0.1:3493
```

The `[ups]` config section is optional and is only needed to override backend parameters such as host, port, poll interval, or command timeout. Manual model/manufacturer/serial configuration is not required.

Example:

```ini
[ups]
host = 127.0.0.1
port = 3493
poll_interval_seconds = 5
command_timeout_seconds = 3
```

### UPS discovery / provisioning

`DH PVE` always exposes:

- `button.dh_pve_scan_ups`
- `sensor.dh_pve_ups_scan_result`
- `sensor.dh_pve_ups_last_scan`

Pressing **Сканировать UPS** performs a read-only `upsc -l` query against the configured NUT endpoint.

Behavior:

- 0 UPS found -> report `UPS не найден`; do not create a new UPS device and do not delete an existing selection.
- 1 UPS found -> persist the NUT UPS name and create/update `DH PVE UPS`.
- More than 1 UPS found -> report `Обнаружено несколько UPS`; do not auto-select or replace an existing selection.
- NUT read failure -> report `NUT недоступен`; preserve any existing selection.

The selected UPS name is stored under `/var/lib/dh_pve_app/` and survives app restarts. Normal polling never deletes Discovery because of a transient NUT/USB failure.

When an UPS is selected, the same process and MQTT connection publish the second logical Home Assistant device:

```text
DH PVE
DH PVE UPS
```

UPS MQTT topics are subordinate to the same app instance:

```text
DigitalHouses/Global/dh_pve_app/<instance>/ups/state
DigitalHouses/Global/dh_pve_app/<instance>/ups/availability
DigitalHouses/Global/dh_pve_app/<instance>/ups/refresh
homeassistant/device/dh_pve_ups_<instance>/config
```

During migration from the earlier alpha identity, the app clears the old retained `homeassistant/device/dh_ups_<instance>/config` Discovery topic so Home Assistant does not retain a duplicate `DH UPS` device.

Discovery is capability-driven. Only variables actually reported by NUT are exposed. Supported normalized facts include UPS status, battery charge/runtime/voltage, load, input/output voltage, nominal real power, warning/low thresholds, test result, and beeper status. NUT status tokens such as `OL`, `OB`, and `LB` are parsed in Python into understandable states and binary sensors; the raw NUT status is retained as an attribute.

The app deliberately does **not** derive active power from `ups.load × ups.realpower.nominal`: live validation showed that some UPS models quantize low load heavily enough for such a derived value to be misleading. `sensor.dh_pve_ups_nominal_real_power` remains a diagnostic hardware fact when NUT reports it.

UPS collection and MQTT publication are separate. NUT is polled frequently, but numeric telemetry is published sparsely on line power and with tighter thresholds while running on battery. Discrete power-state changes publish immediately. A NUT read failure affects only `DH PVE UPS`; `DH PVE` continues operating normally.

This alpha contains **no** UPS power-control path: it does not enable or control `upsmon`, FSD, Proxmox shutdown, guest shutdown, battery tests, beeper control, outlet control, `upscmd`, or `upsrw`. Shutdown coordination is a separate later phase after physical testing.

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

When an UPS has been selected, `DH PVE UPS` additionally exposes:

- `button.dh_pve_ups_refresh`
- `sensor.dh_pve_ups_last_refresh`

UPS refresh is independent and advances its timestamp only after a successful NUT read. If the UPS is selected for the first time after MQTT is already connected, the app subscribes its refresh topic immediately; no MQTT reconnect is required.

## Home Assistant package

The example package is:

```text
dh_pve_app/examples/packages/dh_app_pve_package.yaml
```

One package is used for the whole application. Because UPS entities use the `dh_pve_ups_*` namespace, existing Recorder globs such as `sensor.dh_pve_*` and `binary_sensor.dh_pve_*` naturally include both PVE and UPS telemetry. A separate `dh_app_ups_package.yaml` is not required.

## Dashboard

The PVE Lovelace view is provided at:

```text
dh_pve_app/examples/dh_pve_dashboard.yaml
```

The separate UPS view is provided at:

```text
dh_pve_app/examples/dh_pve_ups_dashboard.yaml
```

The UPS view keeps operational facts prominent (`status`, battery, runtime, load and input/output voltage) and moves service facts such as NUT availability, battery voltage, nominal power, configured NUT thresholds, test result and refresh timestamp into secondary diagnostics. It never uses estimated active power.

The PVE dashboard requires the HACS cards **Mushroom**, **auto-entities**, **mini-graph-card**, and **Entity Progress Card**. The UPS view requires **Mushroom** and **mini-graph-card**.

The dashboards use Python-normalized values directly. Home Assistant does not recalculate infrastructure health or UPS telemetry.

Notifications remain deferred until shutdown/power-loss behavior can be tested on a physically accessible site.

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

The installer does not install/configure NUT, edit `/etc/nut/*`, or enable `nut-monitor`. Current UPS functionality remains read-only.

The service intentionally runs as root because SMART, `/etc/pve` guest configuration, passthrough inspection, and future host-level diagnostics require host access.

## Validation

The installer does **not** disable, edit, or remove the legacy `digitalhouses-proxmox-mqtt.sh` cron job. Compare the new `DH PVE` device against legacy entities before any cutover.

Basic service diagnostics:

```bash
systemctl status dh_pve_app --no-pager
journalctl -u dh_pve_app -n 100 --no-pager
```

For UPS validation, verify the local NUT source independently:

```bash
upsc -l 127.0.0.1:3493
upsc ups@127.0.0.1:3493
```

Expected behavior is `DH PVE` plus an optional `DH PVE UPS` device only after a successful single-UPS scan, capability-driven entities matching the actual UPS, and uninterrupted PVE monitoring if NUT becomes unavailable.

## Status

Version `0.2.0-alpha` is a validation build for read-only NUT-backed UPS telemetry, manual UPS discovery, and HA visualization. NUT bootstrap, coordinated shutdown/FSD policy, automatic LAN secondary provisioning, and notifications remain separate later phases.
