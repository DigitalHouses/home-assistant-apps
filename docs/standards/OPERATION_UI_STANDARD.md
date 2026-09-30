# DigitalHouses Operation UI Standard

**Status:** Normative UI/UX contract  
**Reference implementation:** DigitalHouses PVE Agent 0.5.42  
**Scope:** User-triggered DigitalHouses operations that take noticeable time, perform external I/O, or can fail independently.

## 1. Goal

A user-triggered operation must look and behave consistently across DigitalHouses products.

The UI must answer three questions without guessing:

1. Is the operation idle or running?
2. Did the last attempt fail?
3. When useful, when did the last successful operation finish?

The product runtime is the source of truth. Home Assistant renders that state; it does not synthesize progress with timers or delays.

## 2. Canonical runtime contract

A long-running operation exposes:

~~~text
button.<prefix>_<operation>
sensor.<prefix>_<operation>_state
~~~

If the operation has a meaningful last-success timestamp, also expose:

~~~text
sensor.<prefix>_last_<operation>
~~~

For the canonical product-level Refresh contract, entity naming is governed by [DigitalHouses Manual Refresh Standard](MANUAL_REFRESH_STANDARD.md):

~~~text
button.<prefix>_refresh
sensor.<prefix>_refresh_state
sensor.<prefix>_last_refresh
~~~

The operation-state sensor is diagnostic state owned by the product runtime.

## 3. Operation-state payload

The canonical retained payload is:

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

Semantics:

- `idle` — no operation is running; the last attempt completed successfully or no attempt has run yet;
- `updating` — the request has been accepted and work is pending/running;
- `error` — the latest attempt failed.

The runtime publishes `updating` before starting external/heavy work.

On success:

~~~text
state = idle
started_at = original start time
finished_at = completion time
duration_seconds = measured duration
error = null
~~~

On failure:

~~~text
state = error
started_at = original start time
finished_at = failure/completion time
duration_seconds = measured duration
error = concise diagnostic text
~~~

An `error` state remains authoritative until the next operation begins.

## 4. Home Assistant action-card pattern

The preferred dashboard pattern is one visible action card whose displayed entity is the operation-state sensor while its tap/click action invokes the button.

Conceptually:

~~~text
display entity -> sensor.<prefix>_<operation>_state
tap action     -> button.press button.<prefix>_<operation>
~~~

This avoids using the stateless button entity as the source of UI status.

The exact card implementation is not normative. Mushroom, native Tile, or another supported frontend may be used if the same behavior is preserved.

## 5. Visual states

### idle

Show the normal action.

Example:

~~~text
Обновить всё
Последнее: 29.09.2026 21:10
mdi:refresh
normal action color
~~~

### updating

Immediately after the runtime reports `updating`:

- primary text changes to an in-progress label;
- secondary text explains current work at a useful semantic level;
- icon changes to a progress/busy icon;
- card becomes visually neutral/grey;
- do not show a fake percentage unless the runtime provides real measurable progress.

Example:

~~~text
Обновление…
Сбор данных PVE и UPS
mdi:progress-clock
neutral/grey
~~~

### error

When runtime reports `error`:

- primary text clearly says the operation failed;
- secondary text shows the runtime error or a concise mapped explanation;
- icon uses an error symbol;
- error presentation is red/error-colored;
- the error remains visible until the next attempt begins.

Example:

~~~text
Ошибка обновления
SMART collection failed for disk ...
mdi:alert-circle
red
~~~

## 6. No frontend-owned operation state

Do not implement operation progress with:

- Home Assistant timers;
- `delay:`;
- assumed durations;
- template booleans that guess whether work is still running;
- optimistic local toggles;
- UI-only state that can disagree with the runtime;
- page refresh/poll loops whose only purpose is to simulate progress.

The frontend may format runtime state but must not invent it.

## 7. Duplicate action handling

The UI may remain clickable while `updating`.

Correctness belongs to the product runtime:

- duplicate presses for the same operation are ignored or coalesced;
- no duplicate heavy operation is queued;
- no second concurrent copy starts unless explicit concurrency is part of the product contract.

The UI may additionally suppress/disable interaction while updating where the frontend supports it cleanly, but runtime duplicate protection remains mandatory.

## 8. Operation naming

Use semantic operation names.

Correct:

~~~text
Refresh
Refresh UPS
Scan UPS
Run Speedtest
Refresh servers
Calibrate fan
Delete telemetry
~~~

Do not call every operation `Refresh`.

A scan, test, calibration, deletion, recovery action, restart, and refresh have different semantics and must remain visibly distinct.

## 9. Confirmation

Confirmation is required when the action can materially affect external state or is destructive.

Typical examples:

~~~text
Delete telemetry
Power cycle / recovery
Restart
Shutdown
Calibration that changes persisted parameters
~~~

Pure read-only Refresh normally does not require confirmation unless the operation is unusually expensive.

Confirmation does not replace operation-state feedback.

## 10. Specialized operation state

Any operation that can take noticeable time or fail independently should use the same state machine.

Examples:

~~~text
sensor.dh_pve_agent_refresh_state
sensor.dh_pve_agent_ups_refresh_state
sensor.dh_pve_agent_ups_scan_state
sensor.dh_internet_app_refresh_servers_state
sensor.dh_internet_app_speedtest_state
~~~

Products do not need to expose state sensors for truly instantaneous local actions where there is no meaningful running state.

## 11. Startup and reconnect

Retained `updating` must never leave the UI permanently stuck after an unclean process restart.

At startup, the product reconciles impossible stale operation state deterministically:

- if no operation is actually running, do not continue publishing stale `updating`;
- publish a truthful final state according to the product recovery/error contract.

MQTT/Home Assistant reconnect republishes state. It does not start the operation.

## 12. Error text

The runtime-provided `error` attribute is diagnostic.

Rules:

- concise;
- no secrets, credentials or tokens;
- no traceback dump in Home Assistant attributes;
- actionable enough to distinguish common failure domains;
- full technical detail belongs in product logs.

The dashboard may translate or simplify known error codes, but must preserve the underlying runtime state.

## 13. Recorder behavior

Operation-state entities are diagnostic/transient control state.

Do not create unnecessary high-frequency state churn.

Expected transitions are sparse:

~~~text
idle -> updating -> idle
idle -> updating -> error
error -> updating -> idle/error
~~~

Do not publish unchanged operation payloads repeatedly from the normal polling loop.

## 14. Reference UX: PVE Agent 0.5.42

PVE 0.5.42 is the reference implementation for this standard.

It demonstrates:

- product-owned retained operation state;
- `idle | updating | error`;
- started/finished timestamps;
- measured duration;
- diagnostic error;
- grey progress card;
- red error state;
- live action text;
- runtime duplicate suppression;
- no HA timers;
- distinct PVE Refresh, UPS Refresh and UPS Scan semantics.

Future implementations should copy the contract, not blindly copy PVE-specific YAML.

## 15. Minimum acceptance tests

~~~text
request accepted -> updating published before work
success -> idle with started_at/finished_at/duration
failure -> error with diagnostic error
error -> remains until next attempt
next attempt -> error changes to updating
duplicate press while updating -> no duplicate concurrent operation
MQTT reconnect -> operation does not restart
product restart -> no stale impossible updating state remains
unchanged idle/error payload -> not continuously republished
UI idle -> normal action presentation
UI updating -> neutral/grey in-progress presentation
UI error -> red/error presentation with runtime error
~~~

## 16. Relationship to product standards

This document defines the common UI/operation-state contract.

Product-specific standards define what the operation actually does.

Examples:

- [DigitalHouses Manual Refresh Standard](MANUAL_REFRESH_STANDARD.md) defines full Refresh semantics;
- Events & Notifications Standard defines machine events and local delivery;
- product runtime contracts define Speedtest, scan, calibration, recovery and other specialized actions.

The same UI contract applies across Apps, Agents, and separate DigitalHouses repositories such as Climate when those products expose qualifying user-triggered operations.
