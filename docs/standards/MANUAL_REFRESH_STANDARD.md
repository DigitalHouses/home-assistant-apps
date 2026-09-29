# DigitalHouses Manual Refresh Standard

**Status:** Approved target contract  
**Date:** 2026-09-29  
**Scope:** Active DigitalHouses Apps and Agents that expose manually refreshable observational state.

Reference implementation: DigitalHouses PVE Agent 0.5.41 / 0.5.42.

## 1. Principle

A product-level **Refresh** has one meaning across DigitalHouses:

> Collect the product current observational state now, publish the resulting authoritative state, and expose the real operation progress.

Refresh is not a restart, recovery action, device-control action, cache-only republish, or UI timer.

Home Assistant sends the command and renders product-owned state. The product runtime owns the operation.

## 2. Canonical Home Assistant contract

For canonical prefix:

~~~text
dh_<function>_<app|agent>
~~~

the product-level Refresh contract is:

~~~text
button.<prefix>_refresh
sensor.<prefix>_refresh_state
sensor.<prefix>_last_refresh
~~~

Example:

~~~text
button.dh_pve_agent_refresh
sensor.dh_pve_agent_refresh_state
sensor.dh_pve_agent_last_refresh
~~~

Existing released compatibility-sensitive IDs may change only through the normal product migration rules.

## 3. Refresh operation state

The runtime owns one retained operation-state payload:

~~~json
{
  "state": "idle",
  "started_at": null,
  "finished_at": null,
  "duration_seconds": null,
  "error": null
}
~~~

Allowed states are exactly:

~~~text
idle
updating
error
~~~

Required transitions:

~~~text
idle/error -> updating -> idle
idle/error -> updating -> error
~~~

Rules:

- publish updating before refresh work starts;
- on success publish idle with started_at, finished_at, measured duration_seconds and null error;
- on failure publish error with timestamps, measured duration and concise diagnostic error;
- error remains authoritative until the next refresh starts;
- no Home Assistant timer clears operation state.

## 4. Full Refresh semantics

Product-level Refresh executes all required observational collectors needed to reconstruct current public state.

Rules:

1. dependency/topology discovery runs before dependent collectors;
2. slow or heavy read-only diagnostics are included when they are part of public product state;
3. manual Refresh bypasses normal collection cadence;
4. manual Refresh uses current samples and does not wait for normal averaging/publication windows;
5. newly collected authoritative state is published;
6. stale cache is not represented as a successful fresh result;
7. work is bounded and sequential unless safe internal parallelism is explicitly designed and tested;
8. the product process/service is not restarted.

PVE reference scope includes topology, guests, host, CPU, memory, storage, fans, SMART/health, disk temperature and GPU. If UPS is configured, the user-visible Refresh-all flow also refreshes UPS state.

## 5. No control side effects

Refresh is observational.

Refresh must not implicitly:

- restart/reboot hosts, VMs, containers, routers, ONTs, services, Home Assistant or the DigitalHouses product;
- power-cycle equipment;
- execute recovery actions;
- change user configuration;
- provision new devices;
- delete state/history;
- trigger destructive maintenance.

Operations with different semantics use distinct controls.

Examples:

~~~text
Run Speedtest
Refresh server catalog
Scan UPS
Calibrate fan
Delete telemetry
Recovery / power cycle
~~~

A specialized subsystem refresh does not replace product-level full Refresh.

## 6. Success and last-refresh timestamp

sensor.<prefix>_last_refresh means the completion time of the last successful product-level manual Refresh.

It advances only when:

- every required collector in the Refresh scope succeeds sufficiently to produce valid current state; and
- required authoritative publication succeeds.

On partial failure:

- refresh_state becomes error;
- last_refresh remains unchanged;
- partial valid state may be published when product availability semantics allow it, but the overall Refresh is not successful.

Startup, periodic collection, reconnect republish and Home Assistant restart do not advance last_refresh.

## 7. Duplicate requests and concurrency

Repeated presses must not queue repeated heavy work.

While the same operation is pending or running:

- duplicate requests are ignored or coalesced;
- current state remains updating;
- no second concurrent full Refresh starts.

Different explicit operations may have independent operation-state sensors when concurrency is safe and semantics are distinct.

PVE examples:

~~~text
PVE full Refresh
UPS Refresh
UPS Scan
~~~

UPS Scan remains a scan/provision operation, not a synonym for Refresh.

## 8. MQTT and restart behavior

For MQTT Discovery products, the normal Refresh button payload is:

~~~text
PRESS
~~~

Operation state is retained so Home Assistant reconnect/restart sees authoritative runtime state.

A stale retained updating state after an unclean product restart must be reconciled deterministically at startup. Home Assistant must not remain permanently showing work that is no longer running.

## 9. UI contract

Dashboards render product-owned operation state.

Recommended behavior:

- idle: normal Refresh action;
- updating: neutral/grey progress presentation, for example Обновление…;
- error: red/error presentation with reported error;
- idle secondary text may show last_refresh.

Do not implement progress using Home Assistant timers, arbitrary delays, guessed durations, or optimistic UI-only state.

## 10. Specialized operations

Long-running specialized operations use the same state shape when appropriate:

~~~text
button.<prefix>_ups_refresh
sensor.<prefix>_ups_refresh_state

button.<prefix>_refresh_servers
sensor.<prefix>_refresh_servers_state
~~~

State shape:

~~~text
idle | updating | error
started_at
finished_at
duration_seconds
error
~~~

Use semantic names: scan is scan, test is run_test/run_speedtest, refresh is refresh.

## 11. Minimum tests

~~~text
startup -> no stale updating state survives
button press -> updating is published before work
full Refresh -> every required observational collector runs
dependency collectors -> run before dependent collectors
manual Refresh -> bypasses normal cadence/publication windows
success -> current authoritative state published
success -> last_refresh advances
success -> operation returns to idle with timestamps/duration
collector failure -> operation becomes error
collector failure -> last_refresh does not advance
publication failure -> Refresh is not marked successful
duplicate press while running -> no duplicate concurrent work
periodic collection -> last_refresh does not advance
HA/MQTT reconnect -> state republish does not perform a new Refresh
~~~

## 12. Current adoption review

| Product | Current state |
| --- | --- |
| PVE Agent | Reference implementation. Full Refresh semantics in 0.5.41; operation-state contract in 0.5.42. |
| Plex Agent | Has product-level Refresh and last-refresh. Align operation-state and end-to-end success semantics. |
| Recorder App | Has full manual refresh and success-only last-refresh semantics. Align canonical product-level UI/entity naming and operation-state contract. |
| Backblaze App | Has manual account Refresh. Align during the active Backblaze standards migration. |
| Internet App | Has specialized Refresh servers but no canonical product-level full Refresh. Add full Refresh without conflating it with Run Speedtest or recovery. |
| Speedtest App | Deprecated; no retrofit required. |
| Climate App | Separate repository; apply this standard during shared-standards alignment. |

## 13. Definition of done

A product is Refresh-contract compliant when:

- one clear product-level Refresh exists where observational state is manually refreshable;
- Refresh means full current observational collection, not restart or republish;
- operation state is idle, updating or error;
- progress/error originates in product runtime;
- duplicate work is suppressed;
- last_refresh advances only after successful full Refresh;
- no control/recovery side effects are hidden behind Refresh;
- tests enforce the contract.
