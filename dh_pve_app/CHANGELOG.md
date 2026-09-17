# Changelog

## Unreleased

- Add canonical `dh_pve_app/dh_app_pve.txt` operational guide. After every successful install/update, `install.sh` regenerates `/root/dh_app_pve.txt` with actual installed version/source/commit plus concise install/update, service/log/config, read-only preflight and uninstall commands.
- Remove `/root/dh_app_pve.txt` during supported uninstall only after MQTT cleanup succeeds, avoiding a stale operational guide after App removal.

## 0.5.1

- Add diagnostic `sensor.dh_app_pve_app_version` on the retained PVE diagnostics group. Its state is read from the App `VERSION` file and shares the same resolved release value as MQTT Discovery `device.sw_version` and `origin.sw_version`.
- Show `App <version>` in the standard PVE host summary between the Proxmox version and primary IP, while hiding the segment for unknown/unavailable version state.
- Add supported `/opt/digitalhouses/dh_pve_app/uninstall.sh`. Normal uninstall removes the service/App only after MQTT cleanup while preserving `/etc/dh_pve_app/` and `/var/lib/dh_pve_app/`; `uninstall.sh --purge` additionally removes configuration/state.
- Make uninstall fail-safe: publish canonical PVE/UPS availability offline, tombstone canonical plus legacy PVE/UPS MQTT Discovery using the App's Python identity/topic/config path, and abort local removal on any cleanup failure. A service that was active before a failed uninstall is started again.
- Keep uninstall outside NUT/FSD/UPS-output ownership and leave shared OS dependencies, Home Assistant and the MQTT broker untouched. CI now validates both installer and uninstaller shell syntax.

## 0.5.0

- **Breaking Event contract:** all new public `dh_pve_app` diagnostic/UPS Events use `schema_version: 2` and carry machine semantics only. App Event payloads no longer generate notification `title`, `message`, `summary`, `details`, `status_ru`, emoji or other localized presentation fields.
- Keep HA-first migration compatibility: install/update the v1+v2-compatible Home Assistant notification locale package before deploying App 0.5.0. The App emits v2 only; HA retains the temporary explicit schema-v1 fallback.
- Convert generic problem transitions to structured previous/current v2 payloads with machine metadata, numeric value/average/threshold facts, timezone-aware `observed_at` and active-problem count.
- Convert retained UPS problem observations/aggregates to machine-only facts and de-duplicate status-derived notifications so `on_battery`, `low_battery`, `overload`, `replace_battery` and `bypass` transitions are represented by canonical UPS status Events rather than duplicate generic Events.
- Add canonical UPS status normalization with deterministic precedence while preserving raw NUT tokens diagnostically. Charger semantics are normalized to `charging`, `discharging`, `floating`, `resting`, `idle` or `unknown`; direct `battery.charger.status` has priority over CHRG/DISCHRG fallback evidence.
- Add `sensor.dh_app_pve_ups_battery_charger_status` and move its Russian label/icon/color presentation into the standard HA UPS dashboard rather than Python-generated prose.
- Add persisted `ups_status_changed` transition tracking with previous/current canonical and raw status lists; first observation establishes a baseline and token-only charger noise does not invent a status transition.
- Add persistent battery discharge sessions with fixed milestones at 90/80/70/60/50/40/30/20/10 percent, aggregate large downward crossings into one `battery_discharge_level_crossed` Event and prevent duplicate milestones across restart.
- Add charge-cycle completion detection and `battery_fully_charged`. A direct charging -> floating/resting transition completes the cycle without requiring `battery.charge == 100`; legacy token-only devices use a guarded stable-idle fallback.
- Add a persisted idempotent machine Event outbox. Retained current state is published before transition Events, failed semantic Event publication is retried before advancing to a newer UPS observation, and restart does not lose pending semantic Events.
- Emit structured `shutdown_committed` only after the fixed software shutdown helper successfully commits, with machine reason/charge/runtime/budget/reserve facts. Native NUT FSD remains distinct and does not by itself create this Event.
- Emit structured `config_changed` v2 with OLD/NEW policy values and previous/current revisions after the durable Apply/reload/verification transaction completes.
- Expand UPS MQTT Event Discovery to `problem_started`, `problem_recovered`, `problem_updated`, `config_changed`, `ups_status_changed`, `battery_discharge_level_crossed`, `battery_fully_charged` and `shutdown_committed`; generic PVE Event Discovery remains the three problem transition types.
- Complete English/Russian HA-owned presentation for canonical UPS status enter/exit transitions, discharge milestones, fully charged, shutdown committed and config changes while preserving `binary_sensor.bs_global_system_boot_completed` as the notification gate.
- Keep UPS acquisition fixed at 10 seconds, Event QoS 1 / `retain=false`, shutdown predicates/helper ACL and the non-destructive validation boundary unchanged.

## 0.4.0

- Replace the previous heavy/adaptive collection direction with the canonical Proxmox VE 8.x file/cache-first runtime: `/proc`/`/sys` and `/etc/pve`/PVE caches are primary sources, while expensive subprocess/API paths are reserved for data that has no cheap source and are never used as permanent fallback loops.
- Freeze collection cadence independently from MQTT presentation: FAST 10 s, UPS 10 s, SLOW 60 s, HEALTH 1 h and event-driven STATIC refresh. Legacy `ups.poll_interval_seconds` remains load-compatible but is ignored and normalized to the fixed 10-second UPS cadence.
- Separate decision/publication windows from collection and move toward domain-local NORMAL/DETAIL MQTT publication, immediate semantic/problem transitions, retained grouped state and explicit Recorder-safe history.
- Migrate public MQTT Discovery identity to canonical `dh_app_pve_*` and `dh_app_pve_ups_*` entity IDs with retained legacy Discovery tombstones instead of leaving orphaned old entities.
- Move problem calculation and threshold semantics into the App, expose App-owned `binary_sensor` problem state and aggregate presentation, and use native MQTT Event entities for `problem_started`, `problem_recovered`, `problem_updated` and UPS `config_changed` transitions.
- Deliver diagnostic MQTT Events with QoS 1 and `retain=false`; Home Assistant Event Discovery also subscribes at QoS 1, while retained aggregate problem state remains the recovery source after HAOS downtime/reconnect.
- Add the reusable HAOS notification package: live `event.*` transitions are boot-gated by `binary_sensor.bs_global_system_boot_completed`, startup reconciliation reads only retained aggregate sensors, and the package emits a transport-neutral `dh_app_pve_notification` event with Russian `title`/`message` plus the original structured diagnostic fields.
- Add the separate HAOS Trigger v2 UI package and dashboard VIEW -> EDIT -> CONFIRM -> APPLY flow. Draft MQTT `number` changes never masquerade as active policy; the read-only `sensor.dh_app_pve_ups_trigger_policy` exposes committed active values and the editor closes only after successful `config_changed` confirmation.
- Keep reusable HAOS packages independent from site-private delivery such as `script.write2log`, Telegram targets and specific `notify.mobile_app` services; a site-local adapter may consume `dh_app_pve_notification` and choose the actual delivery transport.
- Preserve capability-driven UPS beeper/test controls while keeping arbitrary shell, arbitrary `upscmd`, UPS load/output-off and generic shutdown commands unavailable to Home Assistant/MQTT.
- Add UPS Trigger Policy v2: software shutdown is `charge threshold OR runtime <= shutdown_budget + reserve`, while native NUT Low Battery remains an independent emergency path and `ignorelb`/synthetic Low Battery overrides remain forbidden.
- Add cheap shutdown-budget acquisition from PVE cache/config plus comparable clean shutdown history and configuration fingerprints; regular Trigger B evaluation no longer requires `qm list`/`pct list` polling.
- Add a fixed immutable FSD boundary through `/opt/digitalhouses/dh_pve_app/bin/dh-pve-ups-policy-cmd dh-pve-ups-shutdown`; a software-trigger shutdown reason is recorded only after the fixed helper succeeds.
- Replace the former ONBATT/upssched mutation product path and root commissioning CLI with HA draft controls for charge threshold/runtime reserve plus an explicit Apply button. The long-running daemon keeps `/etc/nut` read-only and existing administrator NUT/upssched content is observational only.
- Make UPS policy Apply a durable two-phase transaction: preserve the previous active policy, request only a fixed `dh_pve_app.service` reload, complete through SIGHUP in the main loop, promote/reread/verify the target policy, publish synchronized state, then emit `config_changed` OLD -> NEW last. No-op Apply performs no reload/revision/event; failed or interrupted transactions roll back conservatively.
- Make Trigger Policy read-only presentation null-safe for Commissioning state where active/draft policy objects may not yet be populated.
- Remove the obsolete `ups_commission.py` and `ups_policy_apply.py` timer writer modules and their superseded ONBATT/upssched mutation tests while preserving read-only preflight, native Low Battery checks, fixed-helper ownership validation and the systemd `/etc/nut` sandbox.
- Add App-owned monthly city line-power statistics persisted on PVE in `line_power_statistics.json`, counting ONLINE, OFFLINE and UNKNOWN time without importing historical Home Assistant data.
- Publish monthly line-power statistics through dedicated MQTT Discovery entities with ONLINE updates every 600 seconds, OFFLINE updates every 10 seconds and immediate state transitions.
- Add the permanent UPS dashboard block `Городская сеть` with `Свет был`, `Света не было`, `Отключений` and `Доступность`, using App-owned monthly facts and remaining visible during an outage.
- Keep routine CI/deploy validation non-destructive: live FSD, UPS output-off, mains-unplug and deep-discharge validation remain a separate reviewed commissioning gate.

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
- Add host, CPU, memory, storage, disk/SMART, GPU/transcoding, and fan collectors.
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
