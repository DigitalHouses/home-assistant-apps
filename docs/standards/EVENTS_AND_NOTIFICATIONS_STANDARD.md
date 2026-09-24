# DigitalHouses Events and Multilingual Notifications Standard

**Status:** Normative repository policy

**Scope:** All DigitalHouses Apps, Linux agents, Home Assistant Apps/packages and other products that generate user-visible notifications.

This standard complements [DigitalHouses Contract Data Policy](CONTRACT_DATA_POLICY.md). Contract data validation rules from that policy apply at every boundary defined here.

---

## 1. Purpose

DigitalHouses products must separate three concerns:

1. **machine event** — factual machine-readable information about what happened;
2. **localized presentation** — human-readable text in the selected installation language;
3. **delivery** — mobile notification, Telegram, file log, persistent notification, email, TTS or another site-specific mechanism.

Canonical flow:

```text
App / Agent
    ↓
machine event
    ↓
Home Assistant locale package
    ↓
localized notification event
    ↓
installation-owned delivery
```

Core rule:

> **The product describes facts. The locale package describes those facts to a human. The installation decides how the notification is delivered.**

The App/Agent must not know the user's presentation language or notification transport.

---

## 2. Terminology

This standard distinguishes two event layers.

### Machine event

A machine event is emitted by the product and carries machine semantics only.

For MQTT-based products the normal Home Assistant representation is an MQTT Event entity such as:

```text
event.dh_app_pve_ups_diagnostic
```

### Localized notification event

A localized notification event is a Home Assistant event-bus event produced by a locale package after machine-contract validation and localization.

Example:

```text
dh_app_pve_notification
```

It is transport-neutral and may be consumed by any installation-owned delivery automation.

Do not confuse the MQTT Event entity with the localized Home Assistant notification event.

---

## 3. Machine events contain facts, not prose

An App or Agent must emit machine semantics only.

A machine event may contain:

```text
schema_version
event_type
observed_at
identifiers
category
severity
previous/current values
numeric measurements
thresholds
reason codes
state lists
revision numbers
source/provenance codes
other event-specific machine fields
```

Example:

```yaml
schema_version: 2
event_type: battery_fully_charged
observed_at: "2026-09-24T20:25:56+05:00"
previous_charge_percent: 99
current_charge_percent: 100
previous_charger_status: charging
current_charger_status: idle
detection_source: charger_transition
```

The product must not emit **user-facing or localized presentation semantics** as part of the machine-event contract.

Presentation-oriented fields commonly include:

```text
title
message
summary
details
emoji
localized labels
status_ru
status_en
problem_text
human-readable translated reason
```

The prohibition is semantic, not a ban on a literal key name. If an upstream machine protocol genuinely defines a field named `message` or `details` as machine data, the product may preserve it when that field is part of the documented machine contract. It must not turn that field into localized user-facing prose inside the producer.

Forbidden presentation example:

```yaml
event_type: battery_fully_charged
title: "UPS battery charged"
message: "Battery charge reached 100%"
```

---

## 4. Event-specific schemas

Each `event_type` has its own schema.

Do not create one universal payload that requires every field used by every event.

For example:

```text
battery_fully_charged
```

must contain only the fields required to describe charge-cycle completion. It must not require unrelated fields such as:

```text
active_problem_count
shutdown_budget_seconds
cpu_temperature
```

unless those fields are explicitly part of that event contract.

Required and optional fields are governed by [DigitalHouses Contract Data Policy](CONTRACT_DATA_POLICY.md).

Missing or invalid required fields are contract errors and must never be replaced with silent fallback values.

---

## 5. Machine event transport

For MQTT-based DigitalHouses products, transient machine events should normally use Home Assistant MQTT Event Discovery.

Canonical event publication:

```text
QoS: 1
retain: false
```

A machine event represents:

> **something that happened**

It is not the authoritative current state.

Current state that must survive reconnects must be published separately through retained sensors, binary sensors or another explicit state contract.

Therefore:

```text
Event       = transition / occurrence
State       = current fact
Retained    = current-state recovery
```

Retained machine-event payloads must not be used as a substitute for authoritative current state.

MQTT Discovery configuration itself may be retained according to normal Home Assistant discovery practice; this rule concerns the transient machine-event payload.

---

## 6. Publication ordering

When one operation changes current state and generates an event, preferred publication order is:

```text
1. update authoritative current state
2. publish synchronized retained state
3. publish transient machine event
```

This allows a consumer that receives the event to observe already-synchronized current state.

If the product uses durable event retry/outbox logic, it must preserve the same semantic ordering and must not advance authoritative event processing in a way that makes a later event overtake an earlier required event.

---

## 7. Localization belongs outside the App/Agent

Human-readable notification text belongs in the Home Assistant presentation layer.

Canonical package layout:

```text
examples/packages/
    <product>_notification_package.yaml

examples/packages/locales/
    ru/
        <product>_notification_package.yaml
    de/
        <product>_notification_package.yaml
    <locale>/
        <product>_notification_package.yaml
```

The default public locale should normally be English.

Example:

```text
examples/packages/dh_app_pve_notification_package.yaml
examples/packages/locales/ru/dh_app_pve_notification_package.yaml
```

Only one locale package for a product is installed in one Home Assistant instance.

Language selection is installation-scoped. The App/Agent must not inspect or depend on Home Assistant user-language settings.

Existing products with an older locale-file layout should converge on the canonical layout during their next relevant notification-contract change; the path change alone must not alter runtime event identities.

---

## 8. Locale packages are interchangeable

Different language versions of one notification package must expose the same:

```text
package key
automation IDs
input machine-event contract
output notification-event contract
```

They may differ only in presentation:

```text
title
message
labels
human-readable formatting
emoji
```

Changing language must not require changing the App/Agent.

Conceptually:

```text
same machine event
       ↓
 ┌─────┴─────┐
 EN locale   RU locale
 └─────┬─────┘
       ↓
same notification contract
```

---

## 9. Locale package responsibilities

The locale package must:

1. receive the product machine event;
2. identify its `event_type`;
3. validate the schema for that exact event type;
4. format valid machine fields;
5. create localized `title` and `message`;
6. emit a product-specific Home Assistant notification event.

Example:

```text
event.dh_app_pve_ups_diagnostic
        ↓
RU notification package
        ↓
dh_app_pve_notification
```

Every normal localized notification event must use the common DigitalHouses Notification Envelope defined in §10.

Example:

```yaml
notification_schema_version: 1
source: dh_app_pve
kind: battery_fully_charged
severity: info
title: "🔋✅ UPS: батарея заряжена"
message: "Заряд: 99% → 100% · режим зарядки: charging → idle."
source_entity: event.dh_app_pve_ups_diagnostic
category: ups
observed_at: "2026-09-24T20:25:56+05:00"
```

At this boundary `title` and `message` are presentation data and are required.

The source machine `schema_version` may be propagated only as explicitly named provenance data when useful, but it must not replace or masquerade as `notification_schema_version`.

Locale packages must not blindly copy the complete machine payload into the notification event through fields such as `raw`, `attributes`, `payload`, `context` or equivalent catch-all passthrough objects. Additional machine context may be exposed only through explicitly selected, documented notification fields. This prevents accidental coupling of the delivery contract to the producer schema and prevents unintended data from crossing the presentation boundary.

---

## 10. DigitalHouses Notification Envelope v1

The localized Home Assistant notification event is a public cross-product contract independent from the source machine-event schema.

All notification-capable DigitalHouses products use the same mandatory envelope.

### Required fields

```yaml
notification_schema_version: 1
source: <stable product notification source>
kind: <stable notification kind>
severity: <info|warning|error|critical>
title: <non-empty localized string>
message: <non-empty localized string>
```

The six fields above are mandatory for every normal notification and for every `contract_error` notification.

Contract rules:

- `notification_schema_version` must be the integer `1` for Envelope v1;
- `source` must be a non-empty stable machine identifier for the producing DigitalHouses product, for example `dh_app_pve` or `dh_internet_app`;
- `kind` must be a non-empty stable machine-readable notification kind;
- `severity` must be exactly one of `info`, `warning`, `error`, `critical`;
- `title` must be a non-empty localized human-readable string;
- `message` must be a non-empty localized human-readable string.

A delivery adapter may therefore consume notifications from different DigitalHouses products without product-specific field mapping.

Conceptually:

```text
PVE ──────┐
Internet ─┼→ Notification Envelope v1 → installation-owned delivery
Plex ─────┘
```

### Optional common fields

The following common fields are optional when their facts exist and are useful:

```text
source_entity
category
observed_at
```

Products may define additional explicit notification fields for structured context, provided that:

- they do not replace any required Envelope v1 field;
- they are documented;
- all locale variants expose the same field semantics;
- they are selected explicitly rather than copied wholesale from the machine payload;
- absence follows the Contract Data Policy and is never repaired with a fabricated value.

### Version independence

`notification_schema_version` versions the localized notification envelope only.

It is independent from:

- machine-event `schema_version`;
- product release version;
- telemetry schema version;
- MQTT Discovery metadata.

A compatibility-breaking change to required envelope fields or their semantics requires a new notification envelope version.

All locale variants of one product must expose the same notification envelope version and semantics.

### Migration

New notification-capable products must implement Notification Envelope v1 from their first release.

Existing products that already emit localized notification events must converge on Envelope v1 in their next notification-contract change. Until migrated, their legacy output is compatibility debt and must not be used as precedent for new products.

A product currently changing its notification architecture is considered in-scope for this migration and must implement Envelope v1 as part of that work.

---

## 11. Contract validation happens before presentation

A locale package must never repair an invalid machine event.

Forbidden when the value is required contract data:

```jinja
{{ title | default('DigitalHouses') }}
{{ count | int(0) }}
{{ reason | default('Unknown') }}
```

Correct behavior:

```text
valid event
    ↓
normal localized notification

invalid event
    ↓
explicit contract_error diagnostic
```

An invalid event must never accidentally become a normal user notification.

This rule is governed by [DigitalHouses Contract Data Policy](CONTRACT_DATA_POLICY.md).

---

## 12. Contract errors

If a locale package receives an invalid event, it must fail visibly.

Recommended diagnostic fields include:

```text
kind: contract_error
category: diagnostic
severity: error
contract
event_type
failure_class
field
source_entity
```

Typical `failure_class` values:

```text
missing_required_field
invalid_type
invalid_value
invalid_schema_version
invalid_retained_aggregate
freshness_timeout
```

The diagnostic must provide enough context to locate the broken contract without exposing credentials, secrets or private payload content.

A contract error is not a substitute for a normal domain event and must be distinguishable from ordinary operational notifications.

---

## 13. Startup reconciliation

Transient Events are not a recovery mechanism for Home Assistant downtime.

A product that needs startup/reconnect notification reconciliation must maintain a separate authoritative retained state.

Example:

```text
live transition
    → transient Event

HA restart / reconnect
    → retained current-state aggregate
    → startup reconciliation
```

Startup reconciliation must never fabricate a healthy state.

For example:

```text
missing problem count != 0
missing active list    != []
missing severity       != warning
missing timestamp      != now()
```

Unknown, stale or malformed retained state must become an explicit diagnostic condition according to the Contract Data Policy.

Where freshness matters, retained state must expose enough timestamp/age information to distinguish current, stale and unknown state.

---

## 14. Notification delivery is outside the product contract

The public DigitalHouses notification architecture ends at the localized notification event.

Example:

```text
dh_app_pve_notification
```

What happens after that is controlled by the Home Assistant installation.

Possible consumers include:

```text
notify.mobile_app_*
Telegram
persistent_notification
email
Slack
file logging
Node-RED
custom automation
speech/TTS
external webhook
```

The product must not require any particular delivery mechanism.

---

## 15. `write2log` is private installation infrastructure

`script.write2log` is not part of the public DigitalHouses repository contract.

It is a private/site-local mechanism used by the repository owner in his own Home Assistant installation.

Therefore:

- `write2log` is not distributed with Apps or Agents;
- public DigitalHouses packages must not depend on it;
- public product documentation must not require it;
- a product must work without `write2log`;
- the `script.write2log` implementation is not published as part of a DigitalHouses product.

A private installation may connect:

```text
dh_app_pve_notification
        ↓
script.write2log
        ↓
private delivery stack
```

but this is installation-owned delivery, not part of `dh_app_pve`.

---

## 16. User-owned notification delivery

Every user must be free to connect a preferred notification mechanism.

Example:

```yaml
automation:
  - alias: PVE notifications to mobile
    triggers:
      - trigger: event
        event_type: dh_app_pve_notification
    actions:
      - action: notify.mobile_app_phone
        data:
          title: "{{ trigger.event.data.title }}"
          message: "{{ trigger.event.data.message }}"
```

This adapter is intentionally outside the reusable product package.

DigitalHouses exposes a stable localized notification event contract instead of forcing users to adopt a DigitalHouses delivery service.

Installation-owned adapters are still contract consumers: they must validate any fields they require and must not repair missing required notification data with silent fallbacks.

---

## 17. No direct delivery from Apps or Agents

Apps and Linux agents must not directly send:

```text
Telegram messages
Home Assistant mobile notifications
emails
persistent notifications
write2log calls
user-facing localized messages
```

unless direct notification delivery is itself the explicit purpose of that product.

For normal DigitalHouses infrastructure products:

```text
App/Agent → machine event
```

is the presentation boundary.

---

## 18. No direct delivery from reusable locale packages

Reusable public locale packages must stop at:

```text
<product>_notification
```

They must not call:

```text
script.write2log
notify.mobile_app_*
notify.telegram
telegram_bot.*
persistent_notification.create
```

as part of the reusable contract.

This keeps localization reusable and delivery installation-specific.

---

## 19. Naming

Each notification-capable product should define stable names for three distinct interfaces.

### Machine event entities

Examples:

```text
event.dh_app_pve_diagnostic
event.dh_app_pve_ups_diagnostic
```

### Machine `event_type`

Examples:

```text
problem_started
problem_updated
problem_recovered
config_changed
ups_status_changed
battery_discharge_level_crossed
battery_fully_charged
shutdown_committed
```

### Localized notification event

Use a product-specific stable Home Assistant event.

Example:

```text
dh_app_pve_notification
```

Do not use machine `event_type` values as localized text.

Once released, these identifiers are compatibility interfaces and must not be renamed casually.

---

## 20. Severity

Notification Envelope v1 uses the canonical severity vocabulary:

```text
info
warning
error
critical
```

Machine-event contracts should use the same vocabulary when severity is part of their machine semantics.

A locale may change presentation:

```text
info     → ℹ️
warning  → ⚠️
error    → ❌
critical → 🚨
```

but must not change the underlying semantic severity.

Severity is machine semantics only when the producer can determine it from the product contract. A locale package must not silently upgrade or downgrade semantic severity for presentation convenience.

---

## 21. Repository requirements

For every product that supports user notifications, the repository must contain:

```text
machine-event producer
machine-event schema/tests
default locale package
negative contract tests
```

Additional locale packages are optional and may be supplied where maintained.

The repository must not require the maintainer's private notification-delivery implementation.

New notification-capable products must follow this standard from their first release.

Existing products must converge when their notification architecture is next materially changed. A product is not considered migrated merely because this document exists; product validation/tests must enforce the applicable contract.

---

## 22. Required tests

Every product using this architecture must test at least:

1. valid machine event → expected machine payload;
2. machine event contains no localized text;
3. every required field is validated;
4. missing required field → explicit contract error;
5. invalid type → explicit contract error;
6. valid falsy values survive unchanged;
7. each locale consumes the same machine contract;
8. each locale exposes the same package key, automation IDs and output contract;
9. malformed events cannot generate a normal notification;
10. notification packages contain no dependency on private delivery mechanisms such as `write2log`;
11. startup reconciliation does not convert unknown state into a healthy state;
12. shipped Home Assistant YAML packages parse successfully;
13. stable public event/entity identifiers are protected by compatibility tests where applicable;
14. every normal localized notification and every `contract_error` notification contains all six required Notification Envelope v1 fields;
15. `notification_schema_version` is the integer `1` in every locale variant;
16. `severity` is restricted to the common vocabulary;
17. `title` and `message` are non-empty;
18. locale packages do not blindly forward the complete source machine payload through `raw` or an equivalent catch-all field.

All locale variants must test the same notification envelope version and required-field semantics.

---

## 23. Canonical architecture

```text
┌──────────────────────────────────────────┐
│ App / Agent                              │
│                                          │
│ authoritative state + machine semantics  │
└───────────────────┬──────────────────────┘
                    │
                    │ machine event
                    │ schema_version + event_type + facts
                    ▼
┌──────────────────────────────────────────┐
│ Home Assistant locale package            │
│                                          │
│ validation + localization                │
│ EN / RU / other locale                   │
└───────────────────┬──────────────────────┘
                    │
                    │ <product>_notification
                    │ Notification Envelope v1
                    ▼
┌──────────────────────────────────────────┐
│ Installation-owned delivery              │
│                                          │
│ mobile / Telegram / log / TTS / etc.     │
└──────────────────────────────────────────┘
```

For the repository owner's private installation:

```text
<product>_notification
        ↓
script.write2log
        ↓
private delivery stack
```

`write2log` is intentionally outside the public DigitalHouses product contract.

---

## 24. Review rule

When reviewing a notification-capable App or Agent, ask three questions:

> **Does the producer emit facts rather than prose?**

> **Can the language be changed without modifying the producer?**

> **Can the user replace the delivery mechanism without modifying the product?**

If all three answers are yes, the design follows the DigitalHouses notification architecture.

Implementation must additionally satisfy the Contract Data Policy: required data fails visibly, optional data remains absent/null according to schema, and presentation never invents domain values.
