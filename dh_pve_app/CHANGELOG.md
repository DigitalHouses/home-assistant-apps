# Changelog

## 0.2.0-alpha

- Add optional read-only UPS monitoring through an existing NUT server using `upsc`.
- Add separate Home Assistant MQTT device `DH UPS` while retaining one `dh_pve_app` process and one MQTT connection.
- Add UPS-specific MQTT state, availability, refresh and Device Discovery topics without changing the existing `DH PVE` topic contract.
- Add vendor-neutral parsing of NUT status tokens and normalized battery, runtime, voltage, load and power telemetry.
- Add capability-driven UPS Discovery so unsupported variables are not exposed as entities.
- Add estimated real power in Python when NUT provides both load percentage and nominal real power.
- Add fixed meaningful-change publication thresholds for UPS percentages, voltages and runtime, with immediate publication for discrete power-state changes.
- Add independent UPS refresh/reconnect handling and persistent last-successful manual refresh timestamp.
- Isolate NUT read failures from PVE monitoring; failed UPS reads do not stop or degrade the `DH PVE` runtime.
- Preserve the last valid UPS capability inventory across transient NUT read failures.
- Add CyberPower/CPS UT2200E fixture coverage based on live `upsc` output from the remote validation site.
- Keep UPS alpha strictly read-only: no `upsmon`, FSD, shutdown, battery-test, beeper, outlet, `upscmd`, or `upsrw` control paths.
- Keep NUT installation and `/etc/nut/*` configuration outside `dh_pve_app`; the installer does not enable or modify `nut-monitor`.
- Defer coordinated shutdown, LAN NUT clients, notifications and UPS dashboard work until physical local testing.

## 0.1.0

- Introduce `dh_pve_app` as a native Proxmox VE Linux agent.
- Define the separate `DH PVE` MQTT device and `DigitalHouses/Global/dh_pve_app/<instance>` namespace.
- Add host, CPU, memory, storage, SMART/disk-health, GPU/transcoding, and fan collectors.
- Add autonomous VM/LXC inventory plus a shared passthrough topology cache.
- Add VM/LXC status polling and targeted guest rescans when a guest transitions to `running`.
- Collapse VM/LXC status polling to one Proxmox `/cluster/resources` query every 30 seconds instead of separate `qm list` and `pct list` calls every 10 seconds.
- Read guest configuration directly from pmxcfs under `/etc/pve` on the normal path, keeping `qm config` / `pct config` only as fallbacks.
- Move expensive guest GPU telemetry to a 30-second schedule while retaining fast polling for cheap CPU/memory/fan collectors.
- Set the new-install SMART polling default to 60 seconds.
- Detect VM `hostpciN` passthrough and preserve LXC shared `/dev/dri` GPU ownership support without site-specific VM lists.
- Add guest physical-disk SMART collection through QEMU Guest Agent and reuse the existing stable disk ID, health, and daily-statistics pipeline.
- Move guest GPU ownership/telemetry onto the shared topology cache so GPU polling does not repeatedly reparse all guest configurations.
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
