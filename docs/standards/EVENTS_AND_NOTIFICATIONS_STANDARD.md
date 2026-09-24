# DigitalHouses Events and Notifications Standard

**Status:** Normative repository policy

**Scope:** DigitalHouses products that expose user-visible events or notifications.

## 1. Principle

Use the simplest possible Home Assistant flow:

```text
machine event
→ trigger.id
→ choose
→ direct action
```

The product publishes machine facts. The local Home Assistant notification package decides the language, text and delivery service.

## 2. Product / Agent

The product owns the machine event:

```text
event_type
timestamps
identifiers
previous/current values
measurements
thresholds
reason codes
other machine facts
```

The product must not depend on a user's notification service, language, Telegram setup, `write2log`, mobile target or other site-specific delivery.

Transient MQTT machine events should use QoS 1 and `retain: false`. Current state that must survive reconnects belongs in retained sensors/binary sensors, not in the event.

## 3. Local Home Assistant package

Each notification-worthy event gets a clear `trigger.id`.

Example:

```yaml
triggers:
  - trigger: event.received
    target:
      entity_id: event.dh_app_pve_ups_diagnostic
    options:
      event_type:
        - battery_fully_charged
    id: battery_full
```

Actions use `choose` with the trigger condition:

```yaml
actions:
  - choose:
      - conditions:
          - condition: trigger
            id:
              - battery_full
        sequence:
          - action: script.write2log
            data:
              title: "🔋✅ UPS: батарея заряжена"
              message: >-
                Заряд:
                {{ trigger.to_state.attributes.current_charge_percent }}%.
```

Event data is read directly from `trigger.to_state.attributes`.

## 4. No extra notification protocol

Do not add an intermediate notification event, envelope, adapter or emit script when a direct action is enough.

Do not repeat the producer's event-schema validation inside the notification automation. The producer and its tests own the machine-event contract.

The local notification package must not invent missing machine values with fallback domain data.

If the event does not occur, the notification automation does nothing.

## 5. Language and delivery

The local package owns:

```text
title
message
emoji
language
delivery action
target
```

Changing language or delivery must not require changes to the App/Agent.

A local package may call any installation-owned service directly, for example:

```text
script.write2log
notify.send_message
notify.mobile_app_*
persistent_notification.create
```

Repository examples may use a simple default action. A site may replace it with its own service.

## 6. Startup / missed events

Live event notifications are transient. If Home Assistant was offline, an old event is not replayed as a new notification.

Current state remains available through the product's state entities.

If a product explicitly needs startup reconciliation, implement it as a separate automation. Do not complicate the normal live-event path.

## 7. Tests

For notification-capable products, tests should verify:

1. the producer emits the documented machine event;
2. machine events contain facts rather than localized presentation;
3. local package triggers use clear `trigger.id` values;
4. `choose` routes each trigger to a direct action;
5. shipped YAML parses successfully;
6. no unnecessary intermediate notification layer is introduced.

Existing products using an older notification architecture should migrate when their notification layer is next changed.

## 8. Review rule

A notification configuration should be understandable by opening the YAML and reading:

```text
which event
→ which trigger.id
→ which message
→ which action
```

If an ordinary notification requires understanding another protocol layer, the design is too complicated.
