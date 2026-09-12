# DH PVE UPS — Policy and Battery-Test Revision

Date: 2026-09-13
Branch: `feature/dh-pve-ups-scan`
Status: authoritative revision of `2026-09-12-dh-pve-ups-control-shutdown-design.md`

## Purpose

This revision supersedes the previous design wherever that design exposed an **Emergency Runtime Reserve** policy control or proposed writing a low-runtime threshold into the UPS.

The production design now relies on the UPS/NUT hardware Low Battery (`LB`) path as the independent emergency fallback. `dh_pve_app` does not override or synthesize LB and does not use `ignorelb`.

## User-facing shutdown policy

Home Assistant exposes only two writable shutdown-policy values:

1. **Wait after utility loss** — `number.dh_pve_ups_policy_on_battery_delay`
   - semantic value: minutes from confirmed `ONBATT` until shutdown commitment;
   - range: 5–60 minutes;
   - step: 5 minutes.
2. **Power restore delay** — `number.dh_pve_ups_policy_power_restore_delay`
   - semantic value: UPS restart/output delay used after a committed full power cycle;
   - range: 60–300 seconds;
   - step: 30 seconds.

Both are draft-only until the explicit **Apply Policy** action succeeds.

The following control is removed from the product contract:

- `number.dh_pve_ups_policy_emergency_runtime_reserve`

No runtime-reserve value is writable through MQTT or Home Assistant.

## Shutdown triggers

Production shutdown has two independent triggers:

### 1. Normal prolonged-outage trigger

- `ONBATT` starts a cancellable `upssched` timer for the configured wait period.
- `ONLINE` cancels that timer while shutdown has not committed.
- Timer expiry invokes the local PRIMARY FSD path.

### 2. Hardware emergency trigger

- The UPS itself reports NUT `LB` when its own battery policy reaches the critical condition.
- `upsmon` on the PRIMARY treats `LB` as the emergency shutdown trigger.
- This path does not depend on `dh_pve_app`, Home Assistant, MQTT, or the `upssched` long-outage timer.

`dh_pve_app` must not:

- enable `ignorelb`;
- write `override.battery.runtime.low`;
- write `battery.runtime.low` as part of Apply Policy;
- synthesize LB from estimated `battery.runtime`;
- delay or cancel an UPS-reported LB shutdown.

The observed UPS runtime estimate remains telemetry only.

## Read-only UPS policy information

The UI should explain how the selected UPS is actually configured rather than pretending all thresholds are application policy.

Where NUT exposes them, publish/read at least:

- `battery.runtime.low` — hardware/UPS low-runtime threshold;
- `battery.charge.low` — low-charge threshold;
- `battery.charge.warning` — warning threshold;
- `ups.delay.shutdown` — UPS output-off delay;
- `ups.delay.start` — UPS output-restore/start delay;
- current `ups.status` and relevant battery-test result data.

These values are read-only diagnostics. Generic NUT values are published exactly as reported; no CyberPower-specific correction branch is allowed.

For the commissioning UPS currently observed on PVE:

- `battery.runtime.low = 600 s`;
- `battery.charge.low = 10 %`;
- `battery.charge.warning = 20 %`;
- `ups.delay.shutdown = 60 s`;
- `ups.delay.start = 120 s`.

These are host facts, not universal defaults.

## Apply Policy safety boundary

Apply Policy may manage only the configuration required for the approved two-value policy and the standard NUT shutdown chain.

It may manage:

- owned directives in `/etc/nut/upsmon.conf`;
- owned rules in `/etc/nut/upssched.conf`;
- the owned local `upssched` command script;
- the UPS restart delay when the selected driver/device supports and verifies the target value;
- application policy metadata under the app state directory.

It must not manage hardware LB thresholds.

The transaction still requires validation, backups, atomic writes, bounded service actions, reread verification, rollback on failure, and active-policy persistence only after successful verification.

Commissioning safety remains unchanged until a separately reviewed live deployment: current host has `nut-monitor` inactive and `SHUTDOWNCMD "/bin/true"`.

## Policy validation after simplification

Validation must include:

- the two writable values are within their hard ranges and steps;
- selected UPS/NUT is available;
- local NUT role/topology is compatible with PRIMARY operation;
- required files/services are present;
- Proxmox guest shutdown budget is readable for diagnostics and commissioning review;
- UPS restart delay is compatible with the selected driver/device and verified after apply;
- `upsmon`/`upssched` target configuration is internally consistent;
- hardware LB remains native and unmodified;
- no HA path exposes FSD, load-off, generic `upscmd`, arbitrary shell, or arbitrary NUT text.

The previous `minimum_emergency_runtime_reserve_seconds` and `recommended_emergency_runtime_reserve_seconds` are removed from the writable-policy validation contract. Guest shutdown budget remains an important read-only commissioning diagnostic.

## Human-readable policy timeline

The backend should support a UI explanation equivalent to:

1. Utility power fails and UPS enters battery mode.
2. The system waits the configured number of minutes.
3. If utility returns before shutdown commitment, the normal timer is cancelled.
4. If the timer expires, shutdown commits.
5. Independently, if the UPS reports Low Battery first, shutdown commits immediately.
6. Once committed, the sequence is irreversible even if utility returns.
7. NUT SECONDARY systems shut down, then Proxmox guests and host shut down.
8. NUT performs the final UPS power-cycle action.
9. UPS restores output after its configured restart delay once utility is available.
10. Firmware power-restore behavior boots PVE and Proxmox starts guests in configured order.

## Battery-test module

Battery testing is a separate subsystem from shutdown policy.

Supported tests remain capability-driven:

- Quick — `test.battery.start.quick`;
- Deep — `test.battery.start.deep`;
- Stop — `test.battery.stop` (control action, not a test type).

### Scheduled tests

For each supported test type Quick and Deep, expose independent schedule configuration:

- interval in days;
- preferred local start time.

Initial defaults:

- Quick: every 30 days at 12:00 local time;
- Deep: every 180 days at 13:00 local time.

An interval of `0` means automatic execution of that test type is disabled.

Time is interpreted in the PVE host local timezone. A test that becomes overdue outside its preferred time must not start immediately at night; it waits until the next eligible preferred-time window.

The scheduler is persistent across app/PVE restarts. Due tests are determined from the last completed/successfully started scheduled execution plus the configured interval, not from an in-memory timer alone.

### Scheduled-test safety gate

Before an automatic test starts, all of the following must be true:

- NUT and selected UPS are available;
- UPS is on utility power (`OL`) and not `OB`/`LB`;
- no battery test is already running;
- selected UPS advertises the requested test capability;
- battery state is not critical/low;
- shutdown/FSD is not in progress.

If the test is due but the safety gate is not satisfied, do not mark it completed. Keep it due and retry only in a later eligible scheduling window.

If Quick and Deep are both due for the same scheduling window, Deep takes priority and Quick must not run immediately back-to-back. The scheduler records the decision explicitly.

Manual Quick/Deep buttons remain available subject to the existing command safety rules.

## Test history

`dh_pve_app` persists the last 10 battery-test executions under its state directory.

Each history record should contain, where available:

- local start timestamp;
- local finish timestamp;
- test type: `Quick` or `Deep`;
- source: `Manual` or `Scheduled`;
- normalized result;
- exact NUT result text when safe to publish;
- duration seconds;
- battery charge before/after;
- runtime estimate before/after;
- load before test;
- failure/skip reason when applicable.

History is bounded to the newest 10 records.

Expose normalized state sufficient for Home Assistant to show:

- Quick interval and preferred time;
- Deep interval and preferred time;
- last Quick result/time;
- next Quick due time;
- last Deep result/time;
- next Deep due time;
- current test state;
- last 10 test records.

The history belongs to `dh_pve_app`; NUT is not assumed to provide historical storage.

## TDD requirements added by this revision

Tests must prove at least:

- the emergency-runtime-reserve MQTT topic/entity no longer exists;
- policy parsing/hash/lifecycle use only the two approved writable values;
- Apply Policy never writes `battery.runtime.low`, `battery.charge.low`, or enables `ignorelb`;
- target NUT configuration preserves native LB handling;
- read-only UPS hardware thresholds are published when present;
- Quick/Deep interval and time settings persist;
- overdue tests do not start outside their preferred local-time window;
- safety-gate failure leaves a test due rather than marking it completed;
- Deep wins when Quick and Deep are simultaneously due;
- restart/reconnect preserves schedules and history;
- history is capped at 10 newest records;
- manual/scheduled source and test result are recorded;
- no test path exposes or invokes FSD/load-off/shutdown commands.

No automated test may intentionally shut down the development PVE host or remove UPS output.