# DigitalHouses Contract Data Policy

**Status:** Normative repository policy  
**Scope:** All DigitalHouses Apps, Linux agents, Home Assistant packages, adapters, telemetry, internal APIs, event payloads, state payloads, notification contracts, and recovery/reconciliation logic.

---

## 1. Purpose

Contract violations must be visible.

DigitalHouses components must not repair, complete, or disguise missing or invalid contract data by silently substituting synthetic values. A damaged or incomplete payload must never look valid merely because downstream code received values such as `0`, `false`, `unknown`, an empty string, a fabricated timestamp, or generic text.

The repository-wide rule is:

> **Required data must fail loudly, optional data must stay absent/null according to its schema, and presentation must never invent domain values. Silent fallback across contract boundaries is prohibited.**

The purpose is operational as much as architectural: silent fallback converts a local, diagnosable contract error into a distributed failure whose real cause is hidden from logs and downstream consumers.

---

## 2. Core invariant

For contract data:

```text
missing fact != domain value
invalid fact != domain value
parse failure != domain value
unknown source state != safe state
```

Absence of evidence must not be converted into a valid business or operational value.

Examples of forbidden substitutions include:

```text
missing charge        -> 0
missing problem count -> 0
missing online state  -> false
missing status        -> "unknown"
missing reason        -> ""
missing timestamp     -> now()
missing title         -> "DigitalHouses"
missing message       -> ""
```

A value such as `0`, `false`, or `unknown` is valid only when it is the actual semantic value defined by the contract, not when it is being used to hide missing or invalid input.

---

## 3. Definitions

### 3.1 Contract data

Contract data is any runtime value whose meaning crosses a component boundary or is consumed by logic outside the code that produced it.

This includes, but is not limited to:

- event payload fields;
- MQTT state and attribute fields;
- telemetry payloads;
- internal API request/response fields;
- notification title/message/severity/reason fields;
- recovery and reconciliation state;
- persisted runtime state used by later processing;
- adapter inputs and outputs;
- timestamps, versions, statuses, counters, durations, identifiers, health states, and decision inputs.

### 3.2 Silent fallback

A silent fallback is any automatic substitution that turns missing, invalid, unparseable, or unavailable contract data into a syntactically valid value without surfacing the contract failure.

Typical examples:

```jinja
{{ value | default(0) }}
{{ value | default('unknown') }}
{{ title | default('DigitalHouses') }}
```

```python
payload.get("count", 0)
payload.get("message", "")
value or 0
status or "unknown"
```

These patterns are prohibited for required contract fields.

### 3.3 Schema-defined configuration default

A configuration default is different from a silent fallback.

A documented default for an optional **configuration parameter** is allowed when the configuration schema explicitly defines it as the intended behavior before runtime processing begins.

Example:

```text
recovery_retry_count omitted in config -> schema-defined default 3
```

This does not authorize inventing observed runtime facts.

### 3.4 Source failover

Failover from one real source to another real source is allowed when it is part of the component design.

Example:

```text
preferred speedtest server unavailable -> select another eligible server
```

Source failover must not fabricate the resulting domain value. Where provenance matters, the active source must remain observable.

---

## 4. Required fields

If a field is required by the schema for a specific event, state, telemetry payload, API operation, or adapter contract, its absence is a contract error.

Forbidden patterns include:

- Jinja `default(...)` for a required field;
- `| int(0)` or `| float(0)` used to replace absence;
- Python `dict.get(key, fallback)` for a required field;
- `value or fallback` when the fallback can hide absence or a valid falsy value;
- empty string placeholders;
- synthetic `unknown`, `clean`, `online`, `false`, or `0`;
- fabricated timestamps;
- generic notification text used because the real required text is missing.

Required fields must be validated before downstream publication or action.

If validation fails, the component must not emit a formally valid downstream payload containing invented values.

---

## 5. Optional fields

Optionality is part of the schema, not a runtime rescue mechanism.

An optional field must follow one explicit contract:

- omitted when unavailable; or
- present with `null` when the schema defines nullable semantics.

The producer must not synthesize a domain value merely to keep downstream code running.

If a consumer cannot operate without an optional field for a specific event type or operation, that field is not optional for that schema and must be promoted to `required`.

---

## 6. Event-specific schemas

Do not use one universal payload containing every possible field for every event type.

Each `event_type` must define its own required and optional fields.

For example, an event such as:

```text
battery_fully_charged
```

must not require, calculate, or fabricate unrelated fields such as:

```text
active_problem_count
```

unless that field is explicitly part of the `battery_fully_charged` contract.

This keeps validation precise and prevents unrelated defaults from spreading through the system.

---

## 7. Type conversion

Type conversion is allowed only after presence has been established.

Allowed:

```jinja
{{ value | int }}
```

when `value` is a required field whose presence has already been validated.

Forbidden:

```jinja
{{ value | default(0) | int }}
```

for a required field.

A conversion failure is also a contract error. It must not become a synthetic domain value.

Code must distinguish:

```text
missing value
invalid value
valid zero
valid false
valid empty value, if the schema explicitly permits it
```

Using truthiness as a substitute for schema validation is unsafe when `0`, `false`, or an empty value may be legitimate.

---

## 8. Presentation and Home Assistant layers

Presentation must not repair upstream domain data.

Home Assistant packages, templates, dashboards, notification rendering, localization, and UI adapters may format valid values, but they must not invent missing contract values.

If required upstream data is missing or invalid:

- do not render it as a normal valid domain value;
- surface a contract/diagnostic failure through the component's defined diagnostics;
- suppress the invalid downstream operation when continuing would publish misleading data.

A visual-only placeholder is allowed when it is clearly presentation metadata and cannot affect automation, telemetry, notification semantics, business logic, or decisions.

Example:

```text
missing icon mapping -> generic UI icon
```

is allowed.

Example:

```text
missing reason -> "Unknown reason"
```

is not allowed when `reason` is contract data.

---

## 9. Delivery adapters

Adapters such as log writers, Telegram delivery, mobile notification delivery, MQTT publishers, and similar integration layers must validate their required inputs.

If `title` and `message` are required by a notification contract, the adapter must reject a call that lacks them.

Forbidden:

```jinja
{{ title | default('DigitalHouses') }}
{{ message | default('') }}
```

The adapter must not transform an upstream contract error into a cosmetically valid notification.

---

## 10. Startup, reconciliation, recovery, and migration

Startup and recovery logic must preserve uncertainty.

Unknown input must remain unknown until a real source establishes the value.

It is prohibited to map absence of a fact to a safe-looking state such as:

```text
0
false
clean
online
healthy
no_problem
fully_reconciled
```

unless that value is actually established by the authoritative source.

Reconciliation must distinguish at least conceptually between:

```text
known current state
known stale state
unknown state
contract error
```

A recovery path must not claim success merely because missing data was replaced with a default.

---

## 11. Last-known values and cached state

Reusing a previously known value is allowed only when the contract explicitly models it as cached or stale data.

A last-known value must not be presented as a fresh observation after the current read failed.

Where cached state is used, the design must preserve enough metadata to distinguish it from current state, for example:

- source timestamp;
- observation timestamp;
- stale flag or equivalent state;
- age;
- source/provenance where relevant.

A read failure must remain observable even when a stale value is retained for continuity.

---

## 12. Diagnostics and failure behavior

Contract failures must be diagnosable at the boundary where they are detected.

Diagnostics should identify, where applicable:

- component;
- contract/schema;
- operation or `event_type`;
- missing or invalid field;
- failure class such as `missing_required_field`, `invalid_type`, or `invalid_value`;
- source context required for diagnosis.

Diagnostics must not leak credentials, tokens, secrets, or sensitive payload content.

The preferred behavior is:

```text
validate -> reject invalid contract -> record diagnostic -> do not publish invented payload
```

not:

```text
read -> substitute defaults -> publish -> fail later
```

---

## 13. Testing requirements

Every contract schema must have negative tests.

At minimum, tests must verify:

1. removing each required field one at a time produces an explicit contract failure;
2. an invalid type for each typed required field is rejected;
3. invalid required data does not produce a downstream event/state/notification with synthetic defaults;
4. optional fields remain omitted or `null` according to the schema;
5. valid falsy values such as `0` and `false` survive unchanged when permitted by the schema;
6. presentation/adapters do not rescue invalid upstream contracts;
7. startup/reconciliation does not convert unknown facts into healthy/safe values;
8. cached/last-known values, when supported, remain distinguishable from fresh observations.

Tests should assert both the failure and the absence of misleading downstream output.

---

## 14. Allowed defaults and exceptions

The following are allowed:

- defaults explicitly defined by a configuration schema;
- purely visual, non-contract UI fallbacks such as a generic icon;
- deterministic formatting choices;
- real source failover explicitly defined by the component;
- derived values calculated from valid source data according to a documented contract;
- an explicit semantic `unknown` value when the schema defines `unknown` as a real domain state and the producer intentionally establishes that state.

The following are not exceptions:

- making a notification look complete;
- keeping an automation running;
- avoiding a template error;
- avoiding a failed test;
- making telemetry parseable;
- hiding an unavailable upstream value;
- replacing a parse error with a safe value.

If a default materially changes domain meaning, it must be part of the explicit schema/design rather than an implementation fallback.

---

## 15. Code review rule

Use this rule during review:

> **Required data must fail loudly, optional data must stay absent/null, and presentation must never invent domain values. Silent fallback across contract boundaries is prohibited.**

Reviewers should specifically search changed contract-handling code for patterns such as:

```text
default(...)
int(0)
float(0)
dict.get(..., fallback)
value or fallback
"unknown"
""
false
0
now()
```

The presence of one of these patterns is not automatically a defect, but when it touches contract data the author must be able to show why it is an actual schema value, configuration default, presentation-only fallback, or explicit source failover rather than a masked contract error.

---

## 16. Repository requirement

This policy is a shared normative contract.

Product-specific code or documentation may impose stricter validation, but must not weaken this rule.

When a product is modified in an area that handles contract data, tests and implementation must be brought into compliance with this policy. New products must comply from their first release.
