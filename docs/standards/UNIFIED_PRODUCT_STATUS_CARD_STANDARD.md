# DigitalHouses Unified Product Status Card Standard

**Status:** Normative target UI/runtime contract  
**Date:** 2026-10-14  
**Scope:** Active DigitalHouses Home Assistant Apps and Linux Agents (including active products in separate repositories).

## 1. Principle

Each product has **one compact status-and-control card** in its Home Assistant dashboard. The product/authoritative platform owns facts, operation lifecycle and results; the dashboard presents them. Reuse the established working PVE Agent, Plex Agent, Internet App and Recorder App patterns. **Do not introduce a second controller, background job or UI-only operation state.**

This is the **aggregate product card**, not a replacement for separate operation-state sensors or dedicated product/problem cards.

- Aggregate card: `sensor.<prefix>_card` with `idle | running | success | error`.
- Individual operation state: `sensor.<prefix>_<operation>_state`, when applicable, retains the existing `idle | updating | error` contract in [Operation UI Standard](OPERATION_UI_STANDARD.md).
- Product-level Refresh semantics are separately defined by [Manual Refresh Standard](MANUAL_REFRESH_STANDARD.md). A card must not silently redefine Refresh as restart, republish or recovery.

The two state machines serve different purposes. Do **not** rename `updating` to `running` in existing operation sensors or use `updating` as the aggregate card state.

## 2. Canonical aggregate entity

For a product's existing canonical HA entity prefix, expose one MQTT Discovery diagnostic sensor:

```text
sensor.<prefix>_card
```

Examples: `sensor.dh_pve_agent_card`, `sensor.dh_plex_agent_card`, `sensor.dh_internet_app_card`, `sensor.dh_recorder_app_card`.

The authoritative runtime-owned payload for an App/Agent foreground operation is:

```json
{
  "state": "idle",
  "operation": null,
  "started_at": null,
  "finished_at": null,
  "duration_seconds": null,
  "error": null
}
```

- `state`: exactly `idle | running | success | error`.
- `operation`: machine-readable semantic action, normally `refresh | check | install | restart` where the product controls that action.
- `started_at`, `finished_at`: real timezone-aware ISO 8601 timestamps or `null`.
- `duration_seconds`: measured numeric duration, not a guess; `null` until known.
- `error`: concise diagnostic without secrets, or `null`.
- An observational Agent may additionally publish `last_collection_at` for the last genuinely completed collection. Apps can use their existing product-specific health entities instead. Never invent freshness from UI redraws.

The product publishes authoritative changes as retained state, restores them on MQTT/HA reconnect, and does not publish one state update per visible timer tick.

## 3. Lifecycle

```text
idle/error/success -> running -> success -> idle
idle/error/success -> running -> error
```

- Only **accepted user-triggered commands** take over the aggregate foreground card. An automatic collection or scheduled version check must not steal it.
- Publish `running` **before** starting slow/external work. Reject/coalesce duplicate work at the runtime boundary.
- On completion publish `success` or `error`, real finish time and measured duration.
- Show a successful result briefly (**5 seconds** in the adopted implementations), then return to `idle`. The product, not an HA automation, owns this transition.
- Keep `error` visible until the next accepted foreground operation; no arbitrary timeout hides it.
- On product restart, reconcile impossible stale `running`. For an external updater/restart worker that genuinely survives the process, use its authoritative completion status; otherwise report the interruption. Reconnecting MQTT must never rerun a command.
- If installation/restart is owned by Supervisor (see §5), its native state is authoritative, not a fabricated App operation completion.

The displayed elapsed clock is **presentation only**: `mm:ss`, updated in the browser approximately once per second while work is observed as running. Use the browser's monotonic clock from the moment the running state is observed, **not** wall-clock subtraction between HA/browser and host timestamps. The final duration comes from the runtime or authoritative platform, never from this UI clock. Do not continuously publish elapsed time through MQTT or Recorder.

## 4. Common UI layout

Reference composition, used consistently across products:

```text
vertical-stack
  custom:button-card             # read-only status
    icon + product name · vInstalled [→ vLatest]
    operation / outcome / error / product health
  custom:mushroom-chips-card     # actions
    Обновить | Версия | [Новая версия] | Перезапуск
```

The common reference YAML uses Mushroom and `custom:button-card >= 5.0` (including `update_timer`); the card body itself is **not clickable**. Keep identical placement/order/behavior of the four chips:

1. **Обновить** — product-level `button.<prefix>_refresh`. It executes the semantics of Manual Refresh Standard; not a restart.
2. **Версия** — `button.<prefix>_check_updates`; check published stable releases, not arbitrary prereleases or floating image tags.
3. **Новая версия** — visible only when the authoritative installer/platform actually reports an installable update. Require confirmation.
4. **Перезапуск** — require confirmation and explain what monitoring/control is interrupted.

Title: product-specific functional icon, human-friendly name, actual installed version and an arrow to a **verified** newer version when available. Invalid/unknown versions are not silently rendered as valid versions. A pending update remains clearly visible after the short success result disappears.

Secondary line (priority by context): current foreground operation and live elapsed clock; measured success result; actionable error; otherwise product-specific health/problem indication, update availability or genuinely observed collection freshness. A transient successful action must not permanently hide an ongoing product fault. If the card entity is `unknown/unavailable`, show loss of connection rather than claiming a successful/healthy state. Operation, product health and connectivity are distinct facts.

Icons and colors: progress clock during an authoritative operation; error/red on failure; short success/check; warning/orange for an update or product warning; functional product icon at idle. Product-specific health and warning icons are allowed without changing the common layout or chip semantics. No fake percentages: display percent only when the Supervisor/worker actually reports one.

Localized labels and explanation belong to the HA dashboard; machine state values remain language-independent.

## 5. Ownership: Agent versus HAOS App

**Linux Agents** own `refresh`, stable-release `check`, `install`, and Agent service `restart` as documented runtime operations; publish aggregate state and reconcile completion across service restarts. Updating or restarting the Agent must not be represented as rebooting its managed host, VMs or underlying service.

**HAOS Apps** own application-level `refresh` and stable-release `check`. **Home Assistant Supervisor owns installation and restart**:

- `update.<supervisor_app_update_entity>` + `update.install` for installation (with `backup: true` where supported);
- `hassio.app_restart` targeting the actual canonical Supervisor installation slug;
- use the native Supervisor update's `in_progress` / real `update_percentage` in the UI;
- do not invent an App-owned installer, self-update/restart mechanism, extra Supervisor privileges or success confirmation when the App is temporarily offline.

An App-specific `binary_sensor.<prefix>_update_available` may describe the verified release check, but an **App installation chip** must be gated by the actual Supervisor `update` entity. The product can report a newer release before Supervisor offers installation; the card must not make a nonworking install button visible.

## 6. Reference implementations and adoption

Current maintained reference YAMLs:

- [PVE Agent](../../digitalhouses_pve_agent/examples/dh_pve_agent_card_ru.yaml)
- [Plex Agent](../../digitalhouses_plex_agent/examples/lovelace/plex_agent_card_ru.yaml)
- [Internet App](../../digitalhouses_internet_app/examples/lovelace/internet_app_card_ru.yaml)
- [Recorder App](../../digitalhouses_recorder_app/examples/lovelace/recorder_app_card_ru.yaml)

These examples establish the working shape, **not a claim that every implementation already passes every clause**. Observed parity gaps (for example PVE's tenths-of-a-second foreground display and product-specific Refresh implementations) should be aligned during the respective product's next focused change without rewriting already functioning business logic.

Backblaze App and active products hosted separately (e.g., Climate) adopt the same contract in their product repos. Deprecated Speedtest App requires no retrofit.

Keep the canonical maintained card YAML in each product's `examples/` and reference/embed it in that product's maintained dashboard. Do not maintain conflicting copies with divergent behavior.

## 7. Acceptance and change control

For each migrated product, product tests and the repository validator should verify:

- diagnostic `sensor.<prefix>_card`, correct states/fields and retained publication;
- accepted action -> running before work -> measured success/error; brief success visibility; sticky error;
- duplicate commands do not launch concurrent duplicate work; background work does not overwrite the foreground;
- lost connection / process restart / surviving installer are represented truthfully; no permanently stale running;
- available-update title/indicator uses real verified version and authoritative installation availability;
- chip order and action targets, confirmation for install/restart, platform ownership rules;
- one-second **UI-only** running clock, measured final duration, no per-second MQTT/Recorder spam;
- product-specific health indication when idle, with no false OK during unknown/unavailable.

Do not make all current products fail CI solely because this target document has been introduced. Add product-specific assertions as each adoption is completed, then enable a blocking repository-wide gate after all active products comply.

Related contracts: [Operation UI Standard](OPERATION_UI_STANDARD.md), [Manual Refresh Standard](MANUAL_REFRESH_STANDARD.md), [Release Policy](RELEASE_POLICY.md), [Product Naming Standard](PRODUCT_NAMING_STANDARD.md).
