# Changelog

## 0.1.0

- Introduce `dh_pve_app` as a native Proxmox VE Linux agent.
- Define the separate `DH PVE` MQTT device and `DigitalHouses/Global/dh_pve_app/<instance>` namespace.
- Add host, CPU, memory, storage, SMART/disk-health, GPU/transcoding, and fan collectors.
- Add autonomous VM/LXC inventory plus a shared passthrough topology cache.
- Add lightweight VM/LXC status polling and targeted guest rescans when a guest transitions to `running`.
- Detect VM `hostpciN` passthrough and preserve LXC shared `/dev/dri` GPU ownership support without site-specific VM lists.
- Add guest physical-disk SMART collection through QEMU Guest Agent and reuse the existing stable disk ID, health, and daily-statistics pipeline.
- Move guest GPU ownership/telemetry onto the shared topology cache so fast GPU polling does not repeatedly reparse all guest configurations.
- Add read-only MQTT Discovery entities for VM/LXC status and summaries plus passthrough diagnostics.
- Add event-driven MQTT publishing with no synthetic state heartbeat and retained LWT availability.
- Add bounded Home Assistant runtime controls plus `button.dh_pve_refresh` and `sensor.dh_pve_last_refresh`.
- Make manual refresh rebuild full topology before guest-dependent SMART/GPU collection.
- Add stable disk identity, per-disk SMART fault isolation, three-scan missing-device confirmation, and daily disk statistics.
- Use storage `used / total` semantics for the Home Assistant UI contract.
- Add semantic `proxmox_*` metadata for monitoring entities, controls, runtime settings, guest inventory, and collector diagnostics.
- Add normalized fan detection status and acronym-safe collector names (`CPU`, `GPU`, `SMART`).
- Rebuild the production Lovelace view `examples/dh_pve_dashboard.yaml` as four continuous columns and add dynamic VM/LXC inventory.
- Dashboard dependencies are Mushroom, auto-entities, mini-graph-card, and Entity Progress Card; infrastructure health remains Python-owned rather than HA-template calculated.
- Add autonomous Proxmox installer, root-documented systemd service, persistent runtime state, repository validator, and CI coverage.
- Preserve the legacy Bash Proxmox-to-MQTT cron job during Phase 1 side-by-side validation.
- Reserve UPS/NUT monitoring for Phase 2 as a separate `DH UPS` MQTT device.
