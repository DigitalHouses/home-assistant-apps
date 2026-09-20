# DH PVE Refresh All and Line-Power Monthly Statistics Design

Date: 2026-09-17
Status: proposed canonical amendment — approved in chat, pending written-spec review
Target: `dh_pve_app` on Proxmox VE 8.x
Branch: `feature/dh-pve-haos-trigger-v2`

## Authority

This document amends the canonical design in:

`docs/digitalhouses_pve_agent/specs/2026-09-15-dh-pve-simplified-runtime-haos-design.md`

It refines the Manual Refresh contract and adds app-owned monthly utility/line-power statistics. Where this document is more specific than the canonical design, this document is authoritative for these two features.

The existing fixed acquisition cadence remains unchanged. The 10-second / 10-minute behavior defined below is a **publication cadence for monthly line-power statistics**, not a new UPS acquisition cadence.

---

## 1. Goals

1. Make a manual Refresh mean exactly one thing to a user: **refresh all current PVE + UPS data now**.
2. Ensure a change to VM/LXC shutdown configuration is reflected immediately after Manual Refresh in:
   - per-guest current shutdown timeout/order;
   - current comparison of last real shutdown duration against the current timeout;
   - guest shutdown budget;
   - full PVE shutdown budget;
   - UPS runtime-trigger threshold.
3. Move monthly city/utility power availability statistics into `dh_pve_app`, close to the authoritative NUT source.
4. Keep Home Assistant as a light presentation client. HA must not own outage accounting or availability arithmetic.
5. Keep normal operation cheap: no faster collection loop and no frequent state-file writes just to make a timer move.

## 2. Non-goals

- Do not infer city power from input voltage thresholds.
- Do not use HA Recorder as the source of truth for monthly power availability.
- Do not make monthly-statistics publication intervals user-configurable.
- Do not increase normal SMART/HEALTH cadence.
- Do not expose arbitrary NUT commands or change shutdown authority.
- Do not reconstruct missing historical month data that the app never observed.

---

## 3. Global Manual Refresh contract

### 3.1 User meaning

Both existing refresh controls are compatibility entry points for the same user action:

```text
button.dh_app_pve_refresh
button.dh_app_pve_ups_refresh
```

Their user-facing meaning is:

```text
Обновить все данные
```

A press on either control requests one global full refresh. Separate retained entity IDs may remain for compatibility, but they must no longer imply different refresh scopes.

### 3.2 Required order

The coordinator performs the refresh in this order:

```text
1. Refresh all PVE collectors
   - STATIC/configuration
   - FAST
   - SLOW
   - HEALTH
   - current VM/LXC runtime state
   - current VM/LXC startup/shutdown configuration
   - shutdown history/evidence view

2. Refresh UPS/NUT current state

3. Recalculate shutdown-derived data from the fresh PVE state
   - current guest shutdown budget
   - full shutdown budget
   - runtime guard threshold
   - readiness / policy presentation

4. Re-evaluate problems/presentation from the refreshed state

5. Force MQTT publication of the refreshed groups

6. Advance the global successful Manual Refresh timestamp
```

Potentially expensive HEALTH work stays sequential. Manual Refresh is explicitly rare and is allowed to do more work than a normal scheduled cycle.

### 3.3 No scheduler wait

Manual Refresh bypasses normal cadence gates and adaptive publication suppression.

A configuration change such as:

```text
VM 110 shutdown timeout: 200 s -> 100 s
```

must not wait for the next 60-second guest cycle. After one full refresh, HA must receive the new current timeout and all dependent shutdown calculations from the same refresh sequence.

### 3.4 Publication coherence

MQTT is not transactional. Do not describe the refresh as atomic.

The ordered publication must nevertheless make the dependency direction clear:

```text
fresh PVE/guest state
-> fresh UPS/NUT state
-> fresh shutdown-derived state
-> diagnostics / last_refresh
```

The global successful `last_refresh` timestamp advances only after every required refresh stage completes successfully enough to publish a coherent full snapshot. If a required stage fails, publish its unavailable/problem state but do not claim a successful full Manual Refresh.

### 3.5 Current guest table semantics

The shutdown-configuration table used to explain the current budget shows only **currently running** VM/LXC guests, because only those guests participate in the current guest shutdown budget.

For each running guest the UI may show:

```text
VM/LXC
Настроено сейчас   = current Shutdown timeout from PVE config
Последний факт     = last real shutdown duration
От текущего лимита = last real duration / current configured timeout
Результат          = last real shutdown result
```

The percentage against the current limit is a presentation comparison. The historical `last_shutdown_timeout_ratio` remains historical evidence against the timeout that was in force during that old shutdown and must not be relabeled as a current-limit percentage.

The card begins with the app-provided current calculated time required to shut down all currently running guests.

---

## 4. Utility/line-power source contract

### 4.1 Authoritative source

Monthly city-power statistics use normalized NUT UPS status, not HA state and not voltage heuristics.

Input to the statistics tracker is tri-state:

```text
OL present -> ONLINE  (city/utility power present)
OB present -> OFFLINE (UPS is supplying the load from battery)
NUT unavailable, or neither OL nor OB can be established -> UNKNOWN
```

`UNKNOWN` is never converted to ONLINE or OFFLINE.

If future UPS/NUT semantics expose a conflicting or ambiguous status, treat it as UNKNOWN and expose diagnostics rather than guessing.

### 4.2 Terminology

Technical entity names use `line_power` / `utility_power` semantics. User-facing Russian text deliberately stays simple:

```text
Свет был
Света не было
Отключений
Доступность
```

The current-state card uses:

```text
Городская сеть работает
Городская сеть отсутствует
Состояние городской сети неизвестно
```

---

## 5. App-owned monthly statistics

### 5.1 Persisted tracker

Add a small app-owned tracker with a dedicated state store, for example:

```text
/var/lib/dh_pve_app/line_power_statistics.json
```

The tracker persists transition/accounting state, not a 10-second time series.

Minimum persisted information:

```text
schema_version
month_key                 # YYYY-MM in PVE local time
tracking_since
last_known_state          # online/offline/unknown
state_since
online_accumulated_seconds
offline_accumulated_seconds
unknown_accumulated_seconds
outages_month
current_outage_started
last_failure
last_restore
last_outage_duration_seconds
estimated_restore
```

Implementation may normalize the exact storage shape as long as the semantics remain testable and migrations are versioned.

### 5.2 Current values are timestamp-derived

Do not write the state file every 10 seconds.

For the active state, current totals are derived as:

```text
persisted accumulated value
+ elapsed time since state_since for the current state
```

Persist on meaningful boundaries such as:

- first valid observation;
- ONLINE/OFFLINE/UNKNOWN transition;
- month rollover;
- other state-schema/migration checkpoints required for correctness.

A process restart must reconstruct the active interval from persisted timestamps rather than needing frequent disk writes.

### 5.3 Availability formula

Monthly availability is calculated by the app:

```text
known_seconds = online_seconds + offline_seconds

availability_percent =
    online_seconds / known_seconds * 100
```

UNKNOWN time is tracked diagnostically but excluded from the availability denominator. Missing telemetry must not become a power outage.

Round the published percentage in the app to a stable presentation precision; initial target is two decimal places.

### 5.4 Outage count

Increment `outages_month` on a confirmed transition into OFFLINE for an outage that starts in the current month.

A continuing outage that began in the previous month contributes OFFLINE duration to the new month but does not become a second physical outage merely because the calendar changed.

### 5.5 Month boundary

Month accounting uses the PVE host's local timezone.

If an ONLINE/OFFLINE/UNKNOWN interval crosses local month midnight, split its duration exactly at the month boundary, close the old month accounting, reset current-month counters, and carry the current power state into the new month.

The current UI title uses a Russian month label supplied by app presentation metadata, for example:

```text
Статистика за сентябрь
```

### 5.6 First partial month

The app must not invent history from the beginning of a month when it did not observe it.

On first deployment/migration, statistics begin at the first trustworthy observation. Until the next full calendar month, expose enough metadata for UI/diagnostics to indicate that the month is partial, for example:

```text
tracking_since
partial_month: true
```

No HA Recorder backfill is required by this design.

### 5.7 Restart while an outage is open

If the app persisted OFFLINE and later restarts with the first trustworthy state ONLINE, the exact utility-restoration instant may be unknowable while the host was down.

For continuity:

- close the open outage at the first trustworthy ONLINE observation;
- mark the restoration as estimated (`estimated_restore: true`);
- do not claim a more precise restoration timestamp than the app observed.

This deliberately favors transparent continuity over fabricated precision.

---

## 6. MQTT / Discovery contract

Add normalized entities under the existing UPS device.

Required current-state entity:

```text
binary_sensor.dh_app_pve_ups_line_power
```

Required current-month entities:

```text
sensor.dh_app_pve_ups_line_power_online_month
sensor.dh_app_pve_ups_line_power_offline_month
sensor.dh_app_pve_ups_line_power_outages_month
sensor.dh_app_pve_ups_line_power_availability_month
```

Recommended supporting diagnostics/presentation entities:

```text
sensor.dh_app_pve_ups_line_power_current_outage_started
sensor.dh_app_pve_ups_line_power_last_failure
sensor.dh_app_pve_ups_line_power_last_restore
sensor.dh_app_pve_ups_line_power_last_outage_duration
```

The monthly duration entities publish numeric seconds with stable units/device metadata. Lovelace may format seconds into `д. HH:MM:SS`; this is presentation formatting, not business logic.

Month metadata (`month_key`, Russian month label, `tracking_since`, `partial_month`) must be available without HA having to reconstruct calendar/accounting logic.

All four monthly summary values should come from one coherent statistics payload/group so a dashboard refresh cannot mix counters from different tracker snapshots.

The app owns these statistics; HA Recorder is not required for their correctness. They are excluded from Recorder by default unless a later explicit reporting requirement adds them to the whitelist.

---

## 7. Statistics publication profile

UPS acquisition remains fixed at the existing 10-second cadence. Only publication of the line-power statistics group adapts.

### 7.1 Utility power present

When the current line-power state is ONLINE:

```text
statistics publication interval = 600 s (10 min)
```

### 7.2 Utility power absent

When the current line-power state is OFFLINE:

```text
statistics publication interval = 10 s
```

This keeps the live outage duration and monthly availability visibly current while the house is running on UPS.

### 7.3 State transitions

Publish immediately on every trustworthy state transition:

```text
ONLINE -> OFFLINE
OFFLINE -> ONLINE
ONLINE/OFFLINE -> UNKNOWN
UNKNOWN -> ONLINE/OFFLINE
```

For `ONLINE -> OFFLINE` the immediate payload already contains the incremented outage counter and outage start timestamp.

For `OFFLINE -> ONLINE` the immediate payload already contains the closed outage duration and recalculated monthly totals/availability.

### 7.4 UNKNOWN cadence

UNKNOWN is a diagnostic state, not an outage. Publish the transition immediately. While UNKNOWN persists, do not use the 10-second OFFLINE publication profile merely because power state is unknown; the current monthly counters are frozen for business accounting until a trustworthy ONLINE/OFFLINE observation returns.

---

## 8. Dashboard contract

### 8.1 Current state

A compact current-state card remains visible regardless of ONLINE/OFFLINE/UNKNOWN.

Examples:

```text
🟢 Городская сеть работает
```

```text
🔴 Городская сеть отсутствует
Без света: 00:13:48
```

```text
⚪ Состояние городской сети неизвестно
```

### 8.2 Monthly statistics

The monthly block is permanent and must never disappear merely because city power is currently absent.

Target 2x2 layout:

```text
Статистика за сентябрь

┌────────────────────────┐  ┌────────────────────────┐
│ 🟢 16 д. 03:06:00      │  │ 🕘 00:27:14           │
│ Свет был               │  │ Света не было         │
└────────────────────────┘  └────────────────────────┘

┌────────────────────────┐  ┌────────────────────────┐
│ 🔴 3                   │  │ 🔵 99,94 %            │
│ Отключений             │  │ Доступность           │
└────────────────────────┘  └────────────────────────┘
```

During an active outage:

- `Света не было` advances with the 10-second publication profile;
- `Доступность` decreases accordingly;
- `Отключений` was incremented once at outage start;
- the whole block stays visible.

When city power is present, the block receives a normal refresh every 10 minutes plus immediate transition updates.

### 8.3 Shutdown table relationship

The UPS/power dashboard also shows the current shutdown-budget explanation separately:

```text
calculated time for all currently running VM/LXC
+ current per-guest configured timeout
+ last real shutdown duration
+ percentage of current timeout represented by the last real duration
+ full PVE shutdown budget
+ user-configured additional headroom
+ resulting UPS runtime trigger threshold
```

The monthly city-power statistics and shutdown-budget explanation are different concerns and must not be merged into one calculation.

---

## 9. Failure semantics

- NUT unavailable does not count as utility power OFFLINE.
- UNKNOWN time does not lower availability percentage.
- Corrupt tracker state must fail closed to a diagnostic/unavailable statistics state; do not silently replace it with fabricated 100% availability.
- A failed persistence write must be logged and surfaced diagnostically; in-memory accounting may continue but must not pretend persistence is healthy.
- Manual Refresh failure must not advance the successful global `last_refresh` timestamp.
- MQTT publication failure keeps the tracker state authoritative locally; retry publication without double-counting transitions/outages.

---

## 10. Test contract

Use TDD.

### 10.1 Refresh All

Tests must prove:

- either refresh button/event requests the same full refresh path;
- all PVE collectors are refreshed regardless of normal scheduler interval;
- guest config is refreshed before shutdown budget is recalculated;
- UPS/NUT refresh follows fresh PVE state;
- adaptive MQTT suppression does not block Manual Refresh publication;
- a current VM/LXC timeout change is visible after one refresh without waiting for SLOW cadence;
- global successful `last_refresh` advances only after the complete refresh sequence succeeds;
- failure/unavailable state is published without falsely claiming full refresh success.

### 10.2 Monthly line-power tracker

Tests must prove:

- OL -> ONLINE;
- OB -> OFFLINE;
- NUT unavailable/ambiguous -> UNKNOWN;
- ONLINE duration accounting;
- OFFLINE duration accounting;
- UNKNOWN excluded from availability denominator;
- outage count increments once per confirmed outage start;
- OFFLINE -> ONLINE closes the outage;
- restart with persisted active state reconstructs elapsed time;
- restart after an open outage can mark estimated restoration;
- local-time month rollover splits intervals correctly;
- cross-month outage is not double-counted as a new physical outage;
- first partial month is marked partial rather than backfilled;
- persistence is transition/checkpoint based, not a 10-second write loop.

### 10.3 Publication profile

Tests must prove:

- ONLINE steady state publishes monthly stats no more frequently than 600 s;
- OFFLINE steady state publishes monthly stats every 10 s;
- ONLINE/OFFLINE/UNKNOWN transitions publish immediately;
- UNKNOWN does not enter the OFFLINE 10-second accounting profile;
- a failed MQTT publish retry does not increment outage count twice.

### 10.4 Dashboard/UI contract

Tests/validator checks must prove:

- monthly statistics card does not use a conditional that hides it during OFFLINE;
- card uses app-owned monthly entities rather than calculating availability from HA history;
- current month label comes from app metadata/presentation contract;
- shutdown table uses current running guests for the current budget view;
- current-limit percentage is based on current timeout, not historical `last_shutdown_timeout_ratio` relabeling.

---

## 11. Canonical invariants added by this amendment

```text
Manual Refresh means Refresh All
both PVE and UPS refresh controls enter the same full-refresh coordinator
full refresh order is PVE/config -> UPS/NUT -> shutdown-derived values -> publication
manual refresh bypasses normal cadence/publication suppression
successful global last_refresh advances only after complete refresh success

line-power accounting is app-owned and NUT-status based
OL=ONLINE, OB=OFFLINE, unavailable/ambiguous=UNKNOWN
input voltage is not a city-power availability heuristic
monthly availability excludes UNKNOWN time
monthly statistics persist on PVE and do not depend on HA Recorder
current active intervals are timestamp-derived, not persisted every 10 s
month boundary uses local PVE time
partial first month is disclosed, not invented

UPS collection cadence remains fixed
line-power statistics publication: ONLINE=600 s, OFFLINE=10 s
all power-state transitions publish immediately
monthly statistics card never disappears because utility power is OFFLINE
```

Any change to these invariants requires an explicit design revision before implementation.
