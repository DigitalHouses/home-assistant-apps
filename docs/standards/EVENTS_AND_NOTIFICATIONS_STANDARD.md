# DigitalHouses Events & Notifications Standard

**Status:** Normative repository policy

**Scope:** All DigitalHouses Apps, Linux agents and other products that publish machine events intended for Home Assistant automation.

This standard complements [DigitalHouses Contract Data Policy](CONTRACT_DATA_POLICY.md).

---

## 1. Principle

DigitalHouses uses the shortest possible notification path:

```text
machine event
→ trigger.id
→ choose
→ direct action
```

The public product publishes facts.

The local Home Assistant installation decides:

- language;
- human-readable text;
- formatting;
- destination;
- delivery service.

There is no intermediate DigitalHouses notification protocol.

---

## 2. Product boundary

A DigitalHouses App or Agent publishes **machine events only**.

The product may publish fields such as:

```text
schema_version
event_type
observed_at
identifiers
category
severity
previous/current values
measurements
thresholds
reason codes
state lists
revision numbers
other event-specific machine fields
```

The product must not publish localized or user-facing presentation as part of the machine-event contract.

Examples of presentation that belongs outside the producer:

```text
localized title
localized message
emoji chosen for presentation
translated status text
user-specific delivery target
Telegram/mobile/write2log routing
```

The prohibition is semantic, not based on literal field names. If an upstream machine protocol genuinely defines a field named `message`, it may remain machine data when that meaning is documented.

---

## 3. Event-specific machine contracts

Each `event_type` has its own machine schema.

Do not create one universal event payload containing unrelated fields.

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

The producer owns correctness of this payload.

Required/optional semantics and the prohibition of silent fallback are governed by [DigitalHouses Contract Data Policy](CONTRACT_DATA_POLICY.md).

A local notification automation consumes the published event contract directly. It does not create a second validation layer for the same event.

If a required field is missing or invalid, that is a producer/product defect. The local package must not hide it by inventing a replacement value.

---

## 4. MQTT Event transport

For MQTT-based products, transient machine events should normally use Home Assistant MQTT Event Discovery.

Canonical event publication:

```text
QoS: 1
retain: false
```

A machine event means:

> something happened

It is not authoritative current state.

Current state that must survive reconnects must be published separately through retained sensors, binary sensors or another explicit state contract.

```text
Event       = transition / occurrence
State       = current fact
Retained    = current-state recovery
```

MQTT Discovery configuration may be retained according to normal Home Assistant discovery practice. The `retain: false` rule above concerns the transient machine-event payload.

---

## 5. Publication ordering

When one operation changes current state and emits an event, preferred order is:

```text
1. update authoritative current state
2. publish synchronized retained state
3. publish transient machine event
```

If durable event retry/outbox logic is used, it must preserve event ordering.

---

## 6. Local Home Assistant notification package

Human-readable notification logic belongs to the **local Home Assistant installation**.

A local package may use any language and any delivery mechanism required by that installation.

Examples:

```text
script.write2log
notify.mobile_app_*
Telegram
persistent_notification
email
Slack
TTS
Node-RED
webhook
other local service
```

This package is installation-specific. It is not part of the public DigitalHouses product contract.

The public App/Agent must work correctly without that package.

---

## 7. Canonical Home Assistant pattern

For each machine event used for notification:

1. create an `event.received` trigger;
2. give it a clear `trigger.id`;
3. route actions using `choose` by `trigger.id`;
4. read event data directly from `trigger.to_state.attributes`;
5. call the final delivery action directly.

Example:

```yaml
automation:
  - id: dh_pve_agent_notifications
    alias: DH PVE Agent · Notifications

    triggers:
      - trigger: event.received
        target:
          entity_id: event.dh_pve_agent_ups_diagnostic
        options:
          event_type:
            - battery_fully_charged
        id: battery_full

    actions:
      - choose:
          - conditions:
              - condition: trigger
                id:
                  - battery_full
            sequence:
              - action: persistent_notification.create
                data:
                  title: "🔋✅ UPS: батарея заряжена"
                  message: >-
                    Заряд: {{ trigger.to_state.attributes.current_charge_percent }}%.
```

The important property is direct traceability:

```text
event
→ trigger.id
→ choose branch
→ final action
```

A person opening the YAML should immediately see which event produces which message and where it is delivered.

---

## 8. Trigger IDs

Every notification trigger must have an explicit, readable `id`.

Examples:

```text
battery_full
power_lost
power_restored
problem_started
problem_recovered
shutdown_committed
```

The ID is local Home Assistant routing metadata. It is not part of the machine-event schema and does not need to equal `event_type`.

Use IDs that make the `choose` block understandable without tracing unrelated templates.

---

## 9. Direct event data access

Notification text should use the machine event directly:

```jinja
{{ trigger.to_state.attributes.current_charge_percent }}
```

Do not introduce:

- Notification Envelope;
- a second DigitalHouses notification event;
- adapters between locale and delivery;
- copies of the whole event payload;
- a second schema-validation layer in Home Assistant.

Jinja may format valid event data for presentation, but it must not silently manufacture missing required machine data.

---

## 10. No notification Envelope

DigitalHouses does **not** define a shared notification Envelope.

The following architecture is not used:

```text
machine event
→ locale package
→ <product>_notification event
→ adapter
→ delivery
```

Fields such as these are not required as an intermediate notification protocol:

```text
notification_schema_version
source
kind
title
message
contract
failure_class
```

If a final delivery service itself requires `title` and `message`, the local automation creates them directly for that action.

---

## 11. No secondary notification events

A local package must not create an additional DigitalHouses Home Assistant event merely to transport already-localized notification data.

For notification delivery, the original machine Event is the trigger and the chosen service is the destination.

This avoids duplicated contracts and duplicated event routing.

---

## 12. No adapters

No DigitalHouses notification adapter layer is required.

The local Home Assistant automation calls the desired service directly.

Examples:

```text
machine Event → script.write2log
machine Event → notify.mobile_app_phone
machine Event → Telegram action
machine Event → persistent_notification.create
```

Changing the delivery mechanism is a local Home Assistant change and does not require changing the App/Agent.

---

## 13. No repeated machine-event validation in the local package

The App/Agent is responsible for publishing a valid event according to its machine schema and tests.

The local package should not duplicate that schema with large Jinja validation trees.

Therefore the normal path is:

```text
valid producer event
→ trigger
→ presentation
→ delivery
```

not:

```text
producer event
→ duplicate schema validator
→ contract_error notification protocol
→ adapter
→ delivery
```

If the producer violates its own required event contract, fix the producer and its product tests.

Do not hide the defect with default values in the local package.

---

## 14. Event absence

If a transient event does not arrive while Home Assistant is unavailable, no live notification is generated for that event.

That is expected Event semantics.

Do not recreate missed transient notifications by replaying retained Event payloads.

---

## 15. Startup reconciliation

If a product requires reconciliation after Home Assistant restart/reconnect, implement it as a **separate automation** from live event notifications.

Example:

```text
live notification automation
    ← transient machine Events

startup reconciliation automation
    ← authoritative retained current state
```

Do not mix startup reconciliation into every live-event branch.

Startup reconciliation must still respect the Contract Data Policy and must not turn unknown state into a fabricated healthy state.

---

## 16. Public vs local responsibility

### Public DigitalHouses product

Owns:

- machine-event semantics;
- machine-event schemas;
- Event Discovery;
- authoritative state used for recovery where needed;
- product tests proving machine-event correctness.

Must not depend on:

- `script.write2log`;
- Telegram;
- a specific `notify.*`;
- a local language;
- a customer-specific Home Assistant automation.

### Local Home Assistant installation

Owns:

- which events are interesting to the user;
- `trigger.id` naming;
- notification language;
- title/message text;
- formatting and emoji;
- final delivery action;
- optional startup reconciliation automation.

---

## 17. Public examples

A product may include optional notification examples for documentation.

An example is not a reusable notification protocol and must not introduce an intermediate DigitalHouses event or Envelope.

Public examples should use a replaceable placeholder/familiar Home Assistant delivery action rather than depend on a private service that users do not have.

The repository owner's actual `script.write2log` package remains private and installation-specific.

---

## 18. Tests and validation

Product tests must prove the **machine-event contract**:

1. correct `event_type`;
2. required machine fields;
3. correct values/types;
4. no localized presentation generated by the producer;
5. event ordering/persistence behavior where relevant.

The shared repository validator does not validate local notification text, local delivery services or installation-specific Home Assistant automations.

Local notification packages may be checked by Home Assistant configuration validation in the installation where they are used.

---

## 19. Migration

New notification-capable products must use this architecture immediately.

Existing products that currently implement:

- Notification Envelope;
- secondary `<product>_notification` events;
- reusable EN/RU notification-contract packages;
- notification adapters;
- duplicated machine-schema validation in HA;

must remove those layers during their next notification-related product change.

A product already undergoing notification development is in scope for this migration now.

Machine-event interfaces remain stable unless a separate product change intentionally modifies them.

---

## 20. Review rule

For notification architecture, ask:

> **Can I open the Home Assistant YAML and immediately see which machine event produces which human message and which final action receives it?**

The preferred shape is:

```text
machine event
→ trigger.id
→ choose
→ direct action
```

If additional DigitalHouses notification events, Envelopes, adapters or validation layers appear between the machine event and the final action, the design should be simplified unless there is a concrete product-specific reason for that extra layer.
