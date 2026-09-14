# dh_pve_app — Adaptive MQTT / Recorder Architecture

Date: 2026-09-14
Status: design approved in discussion; implementation not started
Repository: `DigitalHouses/home-assistant-apps`
Target app: `dh_pve_app`

## 1. Goal

Redesign only the MQTT / Home Assistant presentation layer of `dh_pve_app` so that:

- internal collectors and raw application logic continue to work with raw measurements as before;
- Home Assistant receives averaged numeric telemetry instead of every raw sample;
- Recorder history becomes smoother and substantially lighter;
- temporal resolution increases only for the resource that actually needs detail;
- application events and discrete state changes remain immediate;
- one publication group cannot update unrelated entities;
- broad Recorder includes such as `sensor.dh_pve_*` remain safe by design;
- manual Refresh still provides a current full snapshot on demand.

The architecture must be reusable as a pattern for other DigitalHouses Apps.

## 2. Core principle

There is no single global "high load" mode that accelerates all telemetry.

Each resource domain owns its own publication profile:

- CPU
- memory
- each disk independently
- each GPU independently
- UPS
- storage capacity where applicable

A busy CPU must not make GPU, disks, RAM, or UPS publish faster unless those resources independently meet their own profile-selection conditions.

`app_profile` is therefore a diagnostic summary, not the control plane for all telemetry.

## 3. Data flow

```text
Collectors / raw application state
        |
        | raw values remain available to internal logic
        v
Presentation Router
        |
        +-- discrete / event / change-only / static paths
        |       -> publish immediately or on change
        |
        +-- numeric continuous telemetry
                |
                +-- Decision Window
                |       -> current averaged decision value
                |       -> Profile Selector + hysteresis
                |
                +-- Publication Average Bucket
                        -> average_window selected by resource profile
                        -> publish only the entities in that publication group
```

Two averaging concepts are deliberately separate:

1. `decision_window` — fixed for a selector and independent of the active profile. It answers: "is this resource under load / in a critical condition?"
2. `average_window` — selected by the active publication profile. It answers: "what temporal resolution should Home Assistant history use now?"

Raw samples are not published as ordinary numeric telemetry.

## 4. Publication profiles

Initial generic profile ladder:

| Profile | Target `average_window` | Purpose |
|---|---:|---|
| `critical` | 15 s | Maximum useful detail during a critical situation |
| `high` | 60 s | Resource is actively loaded / approaching a limit |
| `normal` | 5–10 min | Ordinary operational history |
| `quiet` | 60 min | Very slowly changing operational telemetry |
| static / inventory | change-only, optional 24 h heartbeat | Hardware/configuration/inventory, not normal telemetry |

The minimum publication window is 15 seconds.

No profile may invent resolution that the source collector does not provide. Therefore:

```text
effective_average_window = max(profile.average_window, source_collection_interval)
```

Examples:

- a 30 s GPU collector cannot create true 15 s GPU history;
- a 60 s storage collector cannot create true 15 s storage history;
- changing publication architecture does not implicitly change raw collection cadence.

## 5. Profile selection is local to each resource

### 5.1 CPU

CPU is one publication group containing the mutually useful diagnostic set:

- CPU usage %
- CPU temperature
- CPU frequency
- CPU throttling state

Profile selection may use:

- averaged CPU usage;
- averaged CPU temperature;
- CPU throttling.

`cpu_throttling=ON` is an immediate critical condition:

- it bypasses waiting for the numeric `decision_window`;
- CPU profile becomes `critical` immediately;
- CPU usage, temperature and frequency are then published at critical resolution subject to source sampling limits;
- throttling itself is a discrete state and publishes immediately.

Starting numeric selector policy to validate in tests/config review:

| Signal | `decision_window` | Enter `high` | Enter `critical` | Exit hysteresis |
|---|---:|---:|---:|---:|
| CPU usage | 60 s | >= 75% | >= 95% | high exit < 60%, critical exit < 85% |
| CPU temperature | 60 s | >= 80 C | >= 90 C | high exit < 75 C, critical exit < 85 C |
| CPU throttling | immediate | n/a | `ON` | leave critical only after throttling clears and numeric conditions permit downgrade |

Exact numeric defaults are configuration policy, not Home Assistant helpers.

### 5.2 Memory

Memory is independent from CPU.

Signals:

- memory used %
- swap usage % where available

Memory on real Proxmox hosts may normally remain around 70–90%, so it must not be treated like CPU load.

Starting publication thresholds should therefore be intentionally high, for example:

| Signal | `decision_window` | Enter `high` | Enter `critical` |
|---|---:|---:|---:|
| memory used | 120 s | >= 92% | >= 97% |

Swap may additionally raise the profile when sustained.

Future administrator notifications such as "memory has remained excessively full for a long period; investigate/clean up" belong to a separate sustained-condition notification policy, e.g. 30–60 minutes. They are not the same thing as publication profiling.

### 5.3 Disks

Each physical disk has its own profile.

A hot NVMe must not accelerate HDD, SSD, or other NVMe telemetry.

Primary selector:

- disk temperature averaged over a decision window;
- immediate SMART/discrete health faults remain separate discrete events.

Existing disk-health temperature classes should be reused rather than duplicated:

- HDD: warning / critical according to the existing health policy;
- SSD: warning / critical according to the existing health policy;
- NVMe: warning / critical according to the existing health policy.

Recommended decision window: approximately 180 s.

Continuous disk telemetry such as temperature uses adaptive averaging. SMART health/status/counters remain change-only/event-oriented.

### 5.4 GPU

Each GPU is independent.

CPU activity must not increase GPU history resolution.

Possible selectors:

- GPU temperature;
- GPU load/transcoding metric where the collector exposes one.

Starting policy:

- `decision_window`: about 60 s;
- high temperature: around 75 C;
- critical temperature: around 85 C;
- transcoding/load may enter `high` when materially active;
- no artificial critical level is required solely for ordinary transcoding activity.

GPU owner is change-only, not averaged.

### 5.5 UPS

UPS has its own profile and does not follow CPU/RAM/disk/GPU load.

Continuous averaged telemetry includes, when supported:

- battery charge;
- battery runtime;
- UPS load;
- battery/input/output voltage;
- input/output frequency.

Discrete states remain immediate, including:

- on battery;
- low battery;
- replace battery;
- overload;
- bypass;
- charging/discharging;
- availability and status changes.

Suggested selector semantics:

- `on_battery` -> at least `high` immediately;
- `low_battery`, `overload`, severe fault/bypass condition -> `critical` immediately where appropriate;
- continuous thresholds may use approximately a 30 s decision window;
- return to a lower profile uses hysteresis / stable recovery, not a single raw sample.

## 6. Entity classification

### 6.1 Continuous numeric telemetry — adaptive average

These entities participate in publication averaging and resource-local profiles:

- CPU usage, temperature, frequency;
- memory usage, swap usage;
- storage usage where a time-series graph is useful;
- per-disk temperature;
- per-GPU temperature and numeric load/transcoding metric;
- per-fan RPM where graphing is useful; fan resolution follows its thermal resource context rather than unrelated CPU load;
- UPS charge/runtime/load/voltage/frequency telemetry.

HA state is the averaged published value.

### 6.2 Change-only

Publish only when the semantic value changes:

- disk health state;
- SMART problem binary state;
- wear and SMART counters when a new observed value actually changes;
- GPU owner;
- guest VM/LXC status;
- VM/LXC summary state;
- passthrough ownership/topology state;
- UPS capabilities and supported-feature state;
- UPS shutdown policy/readiness state;
- UPS configuration-derived state;
- beeper/test result where semantically stateful.

### 6.3 Event-only

Publish when the event occurs:

- boot event / last boot transition;
- previous shutdown result;
- shutdown-history changes;
- per-guest shutdown result/timing;
- UPS scan result;
- UPS test completion / test-history change.

### 6.4 Static / inventory

Publish on startup, detected change, manual refresh, and optionally a low-frequency heartbeat such as 24 h only where useful:

- system manufacturer/model/board;
- CPU model/topology inventory;
- installed memory inventory;
- kernel / Proxmox version;
- primary IP where treated as inventory;
- disk model/serial/type/device path;
- UPS manufacturer/model/serial/driver/nominal specifications;
- static capability thresholds and delays.

Static values are never averaged.

### 6.5 Controls

Controls remain command/config entities, not telemetry:

- Refresh;
- UPS scan;
- UPS test buttons;
- UPS test schedule numbers/times;
- raw collection interval controls that remain part of the supported runtime settings.

The old `*_publish_delta` controls belong to the old delta-based publication policy and should be removed/tombstoned as part of migration once compatibility impact is handled.

### 6.6 Debug / publication diagnostics

Keep diagnostic visibility but keep payloads compact:

- collector availability states;
- `sensor.dh_pve_app_profile`;
- `sensor.dh_pve_last_publication`;
- existing refresh timestamps where useful.

## 7. `sensor.dh_pve_app_profile`

`app_profile` is a human/debug summary.

State:

- highest active effective level across resources: `normal`, `high`, or `critical`;
- `quiet` may be represented if useful, but ordinary UI can treat it as normal/low-activity.

Attributes should identify the cause without turning the entity into a high-frequency telemetry container, e.g. conceptually:

```text
cpu=critical
memory=normal
disk:nvme0=high
disk:sda=normal
gpu:0=normal
ups=normal
reason=cpu_throttling
```

The entity publishes on meaningful profile transition, not on every decision-window recalculation.

Do not place continuously changing raw decision averages in attributes.

## 8. `sensor.dh_pve_last_publication`

Required diagnostic timestamp.

State:

- timestamp of the last successful MQTT state-group publication.

Compact attributes may include:

- group;
- reason;
- effective profile.

Typical reasons:

- `average_window_complete`;
- `change`;
- `event`;
- `profile_transition`;
- `manual_refresh`;
- `startup`.

This entity makes it visible in HA when the App last actually updated presentation state.

## 9. Manual Refresh semantics

The Home Assistant Refresh button is an explicit operator request for current truth.

On Refresh:

1. run all available collectors immediately;
2. publish the current factual state of all supported publication groups immediately;
3. numeric values for this manual snapshot may use the freshly collected current value rather than waiting for the publication average bucket, because the user explicitly asked for "now";
4. do not discard/reset the existing rolling decision windows or publication accumulators merely because Refresh was pressed;
5. do not switch a numeric profile from one isolated raw sample unless an immediate discrete critical condition exists;
6. update `last_publication` with reason `manual_refresh`.

Thus normal history stays averaged, while Refresh remains operationally useful.

## 10. Profile transitions and averaging

### Entering a more detailed profile

When a selector moves, for example, from `normal` to `high` or `critical`:

- publish an averaged current value immediately at the transition boundary;
- do not publish a raw numeric sample merely to make the transition visible;
- start a new publication bucket using the new shorter `average_window`.

### Returning to a less detailed profile

- require hysteresis / stable recovery;
- close the current short bucket cleanly;
- start the new longer bucket;
- do not allow oscillation around thresholds to continuously switch publication cadence.

### Identical averaged values

`average_window` defines the maximum desired temporal resolution, not an obligation to generate meaningless Recorder writes.

At bucket close, the App may suppress an MQTT state publication when the rounded Home Assistant state and all recorder-safe semantic attributes are unchanged, unless the publication was explicitly required by an event/profile transition/manual refresh/startup policy.

This preserves graph correctness while minimizing Recorder writes.

## 11. Publication groups / MQTT topics

Replace the current monolithic "one PVE state payload" / "one UPS state payload" behavior with independent retained state groups.

Target topic structure is conceptually:

```text
.../<instance>/state/host
.../<instance>/state/cpu
.../<instance>/state/memory
.../<instance>/state/storage/<id>
.../<instance>/state/disk/<id>/telemetry
.../<instance>/state/disk/<id>/status
.../<instance>/state/gpu/<id>/telemetry
.../<instance>/state/gpu/<id>/status
.../<instance>/state/fans
.../<instance>/state/guest/vm/<id>
.../<instance>/state/guest/lxc/<id>
.../<instance>/state/guest/summary
.../<instance>/state/topology
.../<instance>/state/shutdown
.../<instance>/state/diagnostics
.../<instance>/ups/state/telemetry
.../<instance>/ups/state/status
.../<instance>/ups/state/config
.../<instance>/ups/state/tests
.../<instance>/ups/state/diagnostics
```

Exact topic naming may be adjusted during implementation for compatibility, but the invariant is mandatory:

> publishing one group must not cause unrelated HA entities to receive a new state message.

Discovery must point each entity at the smallest appropriate state group.

## 12. Attribute policy

Broad Recorder include must be safe even if it captures every `dh_pve_*` sensor/binary sensor.

Therefore:

### Continuous numeric sensors

- state = averaged numeric value;
- attributes = stable identification / UI metadata only;
- no high-frequency raw numbers in attributes.

Examples of volatile attributes that should not remain attached to an averaged percentage entity:

- `used_gib` changing on every memory/storage sample;
- volatile status values unrelated to the state;
- raw telemetry duplicated as attributes.

If a volatile numeric value is worth recording, expose it as its own properly averaged entity or do not expose it to Recorder.

### Event/change-only entities

May have richer compact attributes when those attributes belong to the event/state itself, e.g. shutdown reason, guest shutdown timing, SMART recommendation/reasons.

### Static/inventory entities

May carry richer stable attributes because they change rarely.

## 13. Home Assistant / Recorder package target

The HA package should remain simple.

Recorder may continue to use broad includes such as:

```text
sensor.dh_pve_*
binary_sensor.dh_pve_*
number.dh_pve_ups_*
time.dh_pve_ups_*
```

Safety must come from entity/publication design, not from maintaining an increasingly fragile Recorder exclusion list.

Publication profile thresholds live in the App configuration/Python policy, not HA helper entities.

The current six HA `input_number` threshold helpers need a reference/compatibility audit during implementation. If they are only legacy package/UI thresholds and do not serve an independent notification function, remove them. If notification thresholds are retained, name and document them clearly as notification policy, not publication/profile policy.

## 14. Current architecture to replace

The present runtime evaluates a publish policy and then publishes broad combined state payloads. Consequently one changed metric can refresh unrelated HA entities.

The current policy is primarily delta-based and exposes `*_publish_delta` settings.

The new design replaces that presentation behavior with:

- resource-local profile selectors;
- independent decision windows;
- profile-selected average windows;
- independent MQTT publication groups;
- immediate discrete/event semantics;
- no unrelated entity refresh.

Collectors, internal raw state and safety/business logic are not redesigned by this work.

## 15. Migration invariants

Implementation must preserve these behaviors unless separately approved:

- entity identity / unique IDs wherever practical;
- UPS shutdown policy and safety logic;
- guest/shutdown history semantics;
- dynamic discovery for disks, GPUs, fans, VMs/LXCs and UPS capabilities;
- retained MQTT state/discovery semantics;
- Refresh functionality;
- existing raw collector intervals by default.

Where a legacy entity is intentionally removed (for example obsolete publication-delta controls or redundant duplicate telemetry), send proper MQTT Discovery tombstones and document the migration.

## 16. Testing requirements

Before implementation is considered complete, tests must cover at minimum:

1. CPU load raises only CPU publication detail.
2. CPU temperature raises only CPU publication detail.
3. CPU throttling immediately sets CPU to `critical` and does not wait for `decision_window`.
4. CPU critical does not accelerate GPU, RAM, disks or UPS.
5. GPU activity does not accelerate CPU or unrelated GPUs.
6. one hot disk accelerates only that disk telemetry.
7. ordinary 70–90% memory use does not incorrectly behave like CPU high load.
8. memory thresholds/hysteresis work at the intended higher levels.
9. UPS discrete battery/fault states publish immediately.
10. numeric continuous states published to HA are averaged except explicit manual Refresh snapshot semantics.
11. profile transitions do not publish raw numeric spikes.
12. effective publication resolution never exceeds raw collection resolution.
13. one MQTT publication group does not update unrelated entities.
14. volatile raw numeric data is absent from continuous-sensor attributes.
15. unchanged averaged state can be suppressed without breaking event/manual/profile-transition publications.
16. Refresh collects and publishes all groups immediately without resetting decision history.
17. `app_profile` reports the maximum active level and cause but does not update continuously with raw decision values.
18. `last_publication` reflects successful group publications with the correct reason.
19. dynamic entity add/remove and tombstones continue to work.
20. existing shutdown/UPS safety tests remain green.
21. broad HA Recorder package remains intentionally simple and contains no requirement for a per-entity exclusion workaround.

## 17. Non-goals

This redesign does not:

- change UPS shutdown ownership/safety architecture;
- change Proxmox collectors solely to chase shorter graph intervals;
- make Home Assistant responsible for publication thresholds;
- turn Recorder into the App decision engine;
- use global PVE load as a reason to increase all telemetry frequency;
- average discrete states, events, controls, inventory, or configuration.

## 18. Resulting operating model

Normal operation:

- App continues collecting raw data internally at configured collector intervals;
- HA receives smooth averaged operational history at roughly 5–10 minute resolution for ordinary telemetry;
- slow/quiet data may be reduced toward 60 minutes;
- static/inventory values are change-only with optional 24 h heartbeat.

When one resource becomes stressed:

- only that resource moves to a more detailed profile;
- `high` normally gives about 1 minute history;
- `critical` gives the minimum 15 second history where raw collection resolution permits;
- CPU throttling is an immediate CPU-critical trigger;
- after stable recovery, hysteresis returns the resource to normal resolution.

When the operator presses Refresh:

- all collectors run;
- all groups publish a current snapshot immediately;
- normal averaged history/profile state remains intact.

This is the canonical architecture to implement next.
