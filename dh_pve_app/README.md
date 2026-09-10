# DH PVE App

`dh_pve_app` is a native DigitalHouses Linux agent for monitoring Proxmox VE and publishing normalized telemetry to Home Assistant through MQTT Discovery.

Phase 1 intentionally runs alongside the legacy Bash Proxmox-to-MQTT script so both implementations can be compared before cutover.

## Public identity

- Home Assistant MQTT device: `DH PVE`
- MQTT base namespace: `DigitalHouses/Global/dh_pve_app`
- Home Assistant entity prefix: `dh_pve_`
- Service: `dh_pve_app.service`
- Config: `/etc/dh_pve_app/dh_pve_app.conf`
- Persistent state: `/var/lib/dh_pve_app/`

## Runtime model

Collectors poll Proxmox/Linux locally, but MQTT state is published only for meaningful changes, discrete events, reconnect restoration, or a manual refresh. Application liveness uses MQTT availability/LWT; there is no periodic state heartbeat.

The manual refresh entity is `button.dh_pve_refresh`.

## Status

Version `0.1.0` is the initial Phase 1 implementation. UPS/NUT support is reserved for Phase 2.
