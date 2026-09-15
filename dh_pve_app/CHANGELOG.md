# Changelog

## Unreleased

- Add capability-driven `switch.dh_pve_ups_beeper` control when NUT exposes paired beeper on/off commands. Commands are executed by `dh_pve_app` on Proxmox and the switch state is confirmed from real `ups.beeper.status` feedback; load and UPS shutdown instant commands remain intentionally unavailable to Home Assistant.
- Extend explicit root UPS/NUT commissioning to manage `/etc/nut/upsd.users` and the App command credentials as part of the same rollback-safe transaction as the shutdown policy.
- Standardize the local UPS control identity on one `dh_primary_user` with `upsmon primary` and `instcmds = ALL`; preserve its existing password or generate a strong password on first commissioning and synchronize it with the selected `MONITOR` entry and App `[ups]` command credentials.
- Restart `nut-server` and perform a non-destructive authenticated NUT protocol probe before completing commissioning; rollback all managed files and service state on authentication or apply failure without leaking credentials in errors.
- Extend read-only UPS policy preflight to verify the managed NUT user, PRIMARY role, `instcmds = ALL`, selected `MONITOR` identity, App command identity and credential consistency.
- Keep the Home Assistant/MQTT command surface restricted by explicit App allowlists despite the administrative NUT user having `instcmds = ALL`; arbitrary `upscmd`, FSD, `load.*`, `shutdown.*` and shell execution remain unavailable.

## 0.3.0

- Replace production monolithic PVE/UPS MQTT state publication with independent retained Recorder-facing groups so one resource update no longer refreshes unrelated Home Assistant entities.
- Add adaptive numeric publication profiles with default average windows of 30 seconds (`critical`), 60 seconds (`high`), 600 seconds (`normal`) and 3600 seconds (`quiet`), always clamped to the real source collector cadence.
- Separate rolling profile-decision windows from HA publication averaging and add hysteresis so transient raw spikes do not churn Recorder history or resource profiles.
- Make CPU, RAM, each physical disk, each GPU and UPS independently profiled; CPU throttling is immediately `critical`, while On Battery/Bypass and Low Battery/Overload trigger immediate UPS profile escalation.
- Average continuous numeric telemetry for normal HA history while keeping discrete/state/event changes immediate and change-only/static data out of periodic churn.
- Add `sensor.dh_pve_app_profile` and `sensor.dh_pve_last_publication` diagnostics, including successful transport retry reporting without resetting publication buckets.
- Add matching UPS diagnostics, `sensor.dh_pve_ups_app_profile` and `sensor.dh_pve_ups_last_publication`, on the grouped UPS diagnostics topic.
- Keep manual Refresh factual and immediate for all supported groups while preserving rolling decision history and normal averaging buckets.
- Route shutdown history into its own retained state group and keep existing shutdown cause/result semantics unchanged.
- Make the shutdown group self-contained by carrying the stable current VM/LXC shutdown configuration (`onboot`, shutdown order and effective timeout) used by shutdown diagnostic entities.
- Make continuous entity attributes Recorder-safe by removing volatile raw numeric attributes that duplicated changing telemetry.
- Retire the six legacy `*_publish_delta` Home Assistant runtime controls; ignore old persisted values and MQTT set topics safely and publish MQTT Discovery tombstones for removed entities during migration.
- Tombstone the legacy retained monolithic PVE and UPS state topics during migration so the broker namespace contains only the grouped production contract.
- Reduce the Home Assistant package to a simple Recorder-only package with broad `dh_pve_*` entity globs; remove the six unused threshold `input_number` helpers and their startup initializer so publication policy has one source of truth in the App.
- Convert UPS telemetry/status/config/tests/diagnostics to independent retained groups while preserving the existing Proxmox-owned NUT PRIMARY/FSD shutdown-safety architecture.
- Keep `sensor.dh_pve_ups_battery_runtime_minutes` as the canonical UPS runtime entity and remove the duplicate seconds-based Recorder entity while retaining raw seconds internally where compatibility requires it.
- Preserve existing raw collector intervals, dynamic entity identity, UPS shutdown ownership, commissioning safeguards, battery-test controls, shutdown history and reconnect behavior.
- Release after live validation on the production home Proxmox host: grouped MQTT migration passed, adaptive normal-profile suppression and Manual Refresh behavior passed, NUT configuration remained unchanged, and Home Assistant Recorder confirmed sparse natural writes rather than raw collector cadence.

## 0.2.0

- Promote the validated `0.2.0-alpha` UPS/NUT feature set to the stable production release without functional code changes.
- Confirm the Proxmox-owned NUT PRIMARY shutdown architecture, read-only Home Assistant observability, persistent shutdown history/readiness diagnostics, and battery-test controls as the production contract.
- Release after successful live deployment on Proxmox VE, production NUT policy validation with no operational issues, and full repository CI before and after integration to `main`.

## 0.2.0-alpha

- Add optional NUT-backed UPS monitoring as a second logical MQTT device, `DH PVE UPS`, while keeping one `dh_pve_app` process and MQTT connection.
- Scope UPS entity IDs under `dh_pve_ups_*` and use the stable Discovery device ID `dh_pve_ups_<instance>`.
- Add read-only UPS scan/selection with `button.dh_pve_scan_ups`; one discovered UPS is persisted while zero/multiple/error scans preserve any existing selection.
- Add capability-driven UPS telemetry for status, battery charge/runtime/voltage, load, input/output voltage/frequency, nominal power, hardware thresholds, test result, beeper and actionable status flags.
- Keep telemetry factual: do not derive active watts from load percentage and nominal real power.
- Add adaptive meaningful-change publication thresholds with tighter behavior while running on battery and immediate publication for discrete power-state changes.
- Isolate NUT failures from the main PVE monitoring runtime and preserve the last valid UPS capability inventory across transient failures.
- Add independent UPS refresh/reconnect handling and persistent last-successful refresh timestamp.
- Add capability-driven Quick/Deep/Stop battery-test controls with a local-time scheduler, safety gate and persistent test history.
- Default scheduled tests to Quick every 30 days at 12:00 and Deep every 180 days at 13:00, with Deep priority when both are due.
- Add NUT shutdown-policy preflight with PVE guest-shutdown budget calculation and native hardware Low Battery validation.
- Add explicit root-only `--ups-policy-commission` for rare administrative configuration of the Proxmox NUT PRIMARY shutdown policy.
- Keep the long-running `dh_pve_app.service` strictly read-only with respect to `/etc/nut`; systemd no longer grants `ReadWritePaths=/etc/nut`.
- Remove Home Assistant/MQTT shutdown-policy Apply controls and editable policy number entities. HA now observes the effective host policy only.
- Publish observed ONBATT wait and UPS restore delay as read-only sensors parsed from the actual NUT configuration.
- Preserve upgrade compatibility by ignoring the legacy `ups.policy_apply_enabled` config key without granting any runtime capability.
- Reuse the transactional NUT policy renderer/applier only from explicit commissioning, never from the daemon or MQTT event path.
- Make commissioning atomic writes preserve the owner/group contract of `/etc/nut` (normally `root:nut`) and mode `0640`; rollback restores content, mode, UID and GID.
- After restarting the UPS driver during commissioning, wait up to 10 seconds for the exact effective hardware restore delay reported by the hardware instead of performing a race-prone one-shot read.
- Keep the static `dh-pve-ups-policy-cmd` helper restricted to the owned `dh-pve-ups-shutdown` timer token and `upsmon -c fsd` action.
- Keep native hardware Low Battery authoritative; do not install `ignorelb` or battery threshold overrides.
- Add persistent PVE boot/shutdown history keyed by the kernel `boot_id`, so restarting or upgrading `dh_pve_app` does not create a false host boot event.
- Classify the previous shutdown as `normal`, `unclean`, `ups_power`, or `unknown`, keep `shutdown_reason` strictly as the observed cause, and keep the host `shutdown_clean` result separate from that cause. If no cause is known, `shutdown_reason` is `unknown`; clean/unclean/insufficient-evidence states are never encoded as causes.
- Treat missing previous-boot journal evidence as `unknown` and never invent a shutdown timestamp from an arbitrary last log line.
- Capture confirmed UPS/FSD facts and outage/FSD/guest/host timing intervals without assuming that every unclean boot was caused by a power failure.
- Read each VM/LXC effective shutdown timeout/order/onboot state and retain the previous shutdown duration, timeout ratio, result and forced/timeout state; use the Proxmox 180-second effective default when `down` is absent.
- Add dedicated `sensor.dh_pve_ups_guest_shutdown_budget` and `sensor.dh_pve_ups_shutdown_readiness` diagnostics. Readiness warns on forced/timeout/near-timeout guests, unavailable budget, a broken production NUT shutdown path, or a UPS-triggered host shutdown whose clean/unclean result failed or is unknown.
- Keep guest shutdown diagnostics read-only; `dh_pve_app` never rewrites VM/LXC `startup` or `down` configuration.
- Add the reusable `examples/dh_pve_shutdown_readiness_card.yaml` for previous host shutdown, timing chain, UPS readiness/budget and dynamic per-guest shutdown diagnostics.
- Add an advanced UPS dashboard with live state, effective shutdown-policy diagnostics, battery-test controls/scheduler, 24-hour graphs and a 72-hour event log.
- Update the shared HA package so Recorder includes all `sensor.dh_pve_*` / `binary_sensor.dh_pve_*` state plus UPS battery-test scheduler `number` / `time` entities.
- Make release/deploy validation non-destructive: verify service, MQTT, NUT telemetry, policy preflight and optional `OL → OB → OL` timer start/cancel only; do not require or invoke FSD/host shutdown testing.

## 0.1.0

- Introduce `dh_pve_app` as a native Proxmox VE Linux agent.
- Define the separate `DH PVE` MQTT device and `DigitalHouses/Global/dh_pve_app/<instance>` namespace.
- Add host, CPU, memory, storage, SMART/disk-health, GPU/transcoding, and fan collectors.
- Add autonomous VM/LXC inventory plus a shared passthrough topology cache.
- Add VM/LXC status polling and targeted guest rescans when a guest transitions to `running`.
- Collapse VM/LXC status polling to one Proxmox `/cluster/resources` query every 30 seconds instead of separate `qm list` and `pct list` calls every 10 seconds.
- Read guest configuration directly from pmxcfs under `/etc/pve/qemu-server` and `/etc/pve/lxc` on the normal path, keeping `qm config` / `pct config` only as fallbacks.
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
- Reserve UPS/NUT monitoring for Phase 2 as a separate logical MQTT device owned by `dh_pve_app`.
