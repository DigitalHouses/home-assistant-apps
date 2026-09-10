# DH PVE App

`dh_pve_app` is a native DigitalHouses Linux agent for Proxmox VE. It collects host, CPU, memory, storage, physical-disk/SMART, GPU, transcoding, and fan telemetry and publishes normalized Home Assistant entities through MQTT Discovery.

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

## Storage semantics

Storage entities use **used / total** semantics. Home Assistant receives ready-to-display `usage_percent`, `used_gib`, and `total_gib`; it does not need templates to calculate infrastructure values. `available_gib` may exist in the internal collector payload but is not the primary storage UI contract.

## Disk health

Disk health is computed by the Python agent and exposed as exactly:

- `HEALTHY`
- `WARNING`
- `CRITICAL`

The health engine evaluates SMART overall status, NVMe critical warnings, wear, media/reallocated/pending/uncorrectable errors, unsafe-shutdown growth, temperature, and counter growth. Daily statistics include maximum temperature and sparse lifetime counters for Recorder-friendly history.

## Manual refresh

Home Assistant exposes:

- `button.dh_pve_refresh`
- `sensor.dh_pve_last_refresh`

A manual refresh runs all enabled collectors and forces a state publication. `last_refresh` advances only after a successful full refresh.

## Dashboard

A production Lovelace view is provided at:

```text
dh_pve_app/examples/dh_pve_dashboard.yaml
```

It requires the HACS cards **Mushroom**, **auto-entities**, and **mini-graph-card**. Dynamic storage, physical disks, GPU, fans, runtime settings, and collector diagnostics are selected through the `proxmox_*` semantic attributes emitted by MQTT Discovery rather than hard-coded hardware entity IDs.

The dashboard uses the Python agent's normalized values directly. Storage is rendered as `used / total`, disk health remains the Python-produced `HEALTHY/WARNING/CRITICAL` state, and Home Assistant does not recompute infrastructure health.

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

Useful diagnostics:

```bash
systemctl status dh_pve_app --no-pager
journalctl -u dh_pve_app -n 100 --no-pager
```

## Status

Version `0.1.0` is the initial Phase 1 implementation. UPS/NUT support is reserved for Phase 2 and will use a separate `DH UPS` MQTT device.
