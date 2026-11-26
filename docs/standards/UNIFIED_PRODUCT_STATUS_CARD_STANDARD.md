# DigitalHouses Unified Product Status Card Standard

**Status:** Normative target UI/runtime contract  
**Date:** 2026-11-26  
**Scope:** Active DigitalHouses Home Assistant Apps and Linux Agents (including active products in separate repositories).

## 1. Principle

Each product has **one compact status-and-control card** in its Home Assistant dashboard. The product/authoritative platform owns facts, operation lifecycle and results; the dashboard presents them. Reuse the established working PVE Agent, Plex Agent, Internet App and Recorder App patterns. **Do not introduce a second controller, background job or UI-only operation state.**

This is the **aggregate product card**, not a replacement for separate operation-state sensors or dedicated product/problem cards.

- Aggregate card: `sensor.<prefix>_card` with `idle | running | success | error`.
- Individual operation state: `sensor.<prefix>_<operation>_state`, when applicable, retains the existing `idle | updating | error` contract in [Operation UI Standard](OPERATION_UI_STANDARD.md).
- Product-level Refresh semantics are separately defined by [Manual Refresh Standard](MANUAL_REFRESH_STANDARD.md). A card must not silently redefine Refresh as restart, republish or recovery.

### Mandatory simplicity and current-state authority

The card is a projection of current product health and actual operation state, not a durable transaction coordinator. This rule applies to all active App and Agent dashboards, including separate repositories. Reuse the actual runtime/worker/Supervisor state; do not create an independent persistent card workflow or duplicate operation lifecycle. Keep the existing public MQTT entities and card layout during migration.

- Start every product process with clean foreground UI state. After startup, publish current version, availability and observed health; show a surviving installer only while its authoritative state says it is active.
- Do not reconstruct stale foreground card operations, match timestamps or transaction IDs solely for the UI, or require historical installation evidence to declare a healthy running product healthy. Timestamps remain optional presentation/diagnostic facts, never completion gates.
- Show actual accepted work while running and actual actionable failures. Internal bookkeeping discrepancies go to logs, not a red user-facing operation error. Never hide a verified failed installation, rollback, product fault or loss of connectivity.
- Refresh completes when its documented collection finishes; version check completes when the release check returns; installation follows the authoritative installer; restart completes when the new process is running and reports fresh state. No manual JSON/MQTT cleanup or HA restart is required.
- Preserve installer safety, backup, rollback, duplicate-command protection and Supervisor ownership. Do not change these merely to simplify presentation.

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
- Keep a verified actionable `error` visible while relevant; clear it on successful retry or authoritative recovery. Never persist a stale UI-only error across a healthy restart.
- On product restart, discard foreground card bookkeeping; derive the card from current runtime and any actually active external worker. Report verified failures from the authoritative owner, not missing card history. Reconnecting MQTT must never rerun a command.
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

### Linux Agent UI fidelity: PVE is the reference

For **Linux Agents**, the maintained
[PVE canonical Dashboard](../../digitalhouses_pve_agent/dashboards/ru/10_pve_proxmox.yaml)
and [PVE reference card](../../digitalhouses_pve_agent/examples/dh_pve_agent_card_ru.yaml)
are the **required starting point** for product status-and-control UX. The
operational reference is the **current** PVE source on `main`, not an
assistant-authored approximation or an earlier release screenshot.

Where applicable, replicate the **actual PVE** control composition and the
user-visible **Russian text** without rewording:

- Same card position and layout, product name/version/`vCurrent → vTarget`
  treatment, status hierarchy, color/icon meaning and available-update
  indication.
- Same chip order and labels: **Обновить · Версия · [Новая версия] ·
  Перезапуск**; equivalent button behavior and confirmation where required.
- Same wording for version-check result, install/restart/refresh progress,
  operation duration, failure and stale/unavailable conditions, and
  time-since-last-collection when that fact is available.
- The Agent, not the frontend, must own the operation's authoritative state,
  real measured duration, error and verified installed/target versions. The
  UI may format a live timer but must not invent completion or data freshness.
- Copy PVE card behavior/format where applicable; substitute only the product
  name, functional icon, entity IDs and truly product-specific facts. Preserve
  the established canonical View/section structure and place added
  product-specific cards within it rather than creating arbitrary new grid
  sections.

These are **behavioral and textual parity requirements**, not a request to
copy PVE's infrastructure probes, UPS safety gates, hardware sections, or
privileged commands into PBS/Plex. A needed exception must be explained
in that product's documentation and exercised by tests. Follow the existing
operation-state contracts in this document and
[Operation UI Standard](OPERATION_UI_STANDARD.md); correct a conflict in the
reference/standard before treating it as a pattern to reproduce.

**Acceptance:** compare rendered/fixture-based HA operation card examples
for idle, update available, check (current/new), running install, completed
install, error, MQTT unavailable and subsequent idle. Check exact
applicable labels, version pairs, chip order, placement and actions against
current PVE. Do not claim parity merely because both cards expose the same
buttons or MQTT fields. Apply product by product rather than adding a
repository-wide CI gate before existing agents are migrated.

CLI parity is separately mandatory under
[Linux Agent Management Standard](DH_LINUX_AGENT_MANAGEMENT_STANDARD.md).

## 5. Ownership: Agent versus HAOS App

**Linux Agents** own `refresh`, stable-release `check`, `install`, and Agent service `restart` as documented runtime operations; publish aggregate state derived from the current runtime and installer, without reconstructing foreground card transactions across service restarts. Updating or restarting the Agent must not be represented as rebooting its managed host, VMs or underlying service.

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
- accepted action -> running before work -> measured success/error; brief success visibility; verified actionable error and automatic recovery;
- duplicate commands do not launch concurrent duplicate work; background work does not overwrite the foreground;
- lost connection / process restart / surviving installer are represented truthfully; no permanently stale running or stale UI-only error;
- successful HA, CLI, automatic or Supervisor update with missing/reordered historical card timestamps still shows the actual installed version and healthy state; an actual failed update remains distinguishable;
- available-update title/indicator uses real verified version and authoritative installation availability;
- chip order and action targets, confirmation for install/restart, platform ownership rules;
- one-second **UI-only** running clock, measured final duration, no per-second MQTT/Recorder spam;
- product-specific health indication when idle, with no false OK during unknown/unavailable.

Do not make all current products fail CI solely because this target document has been introduced. Add product-specific assertions as each adoption is completed, then enable a blocking repository-wide gate after all active products comply.

Related contracts: [Operation UI Standard](OPERATION_UI_STANDARD.md), [Manual Refresh Standard](MANUAL_REFRESH_STANDARD.md), [Release Policy](RELEASE_POLICY.md), [Product Naming Standard](PRODUCT_NAMING_STANDARD.md).
