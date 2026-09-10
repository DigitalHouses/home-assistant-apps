# Changelog

## 0.1.0

- Introduce `dh_pve_app` as a native Proxmox VE Linux agent.
- Define the separate `DH PVE` MQTT device and `DigitalHouses/Global/dh_pve_app/<instance>` namespace.
- Add host, CPU, memory, storage, SMART/disk-health, GPU/transcoding, and fan collectors.
- Add event-driven MQTT publishing with no synthetic state heartbeat and retained LWT availability.
- Add bounded Home Assistant runtime controls plus `button.dh_pve_refresh` and `sensor.dh_pve_last_refresh`.
- Add stable disk identity, per-disk SMART fault isolation, three-scan missing-device confirmation, and daily disk statistics.
- Use storage `used / total` semantics for the Home Assistant UI contract.
- Add autonomous Proxmox installer, root-documented systemd service, persistent runtime state, repository validator, and CI coverage.
- Preserve the legacy Bash Proxmox-to-MQTT cron job during Phase 1 side-by-side validation.
- Reserve UPS/NUT monitoring for Phase 2 as a separate `DH UPS` MQTT device.
