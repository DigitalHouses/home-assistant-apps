# dh_pve_app Adaptive MQTT / Recorder Architecture v2

Date: 2026-09-14
Status: approved for implementation
Target: `dh_pve_app`

## Goal

Keep collectors and internal raw application logic unchanged, but replace the MQTT/Home Assistant presentation layer so that HA receives smooth, averaged numeric telemetry with adaptive temporal resolution while discrete/event data remains immediate.

Primary outcomes:

- minimal Recorder writes;
- smooth graphs;
- more detail only for the resource actually under load or in trouble;
- broad Recorder globs such as `sensor.dh_pve_*` remain safe by entity design;
- manual Refresh always gives a factual current snapshot;
- profile thresholds/windows live in the App, not in HA helpers;
- later tuning changes parameters, not architecture.

## Core model

Each resource owns an independent publication profile. There is no global high-load switch that accelerates unrelated telemetry.

Independent resource domains:

- CPU;
- RAM;
- each physical disk;
- each GPU;
- storage usage;
- UPS.

A busy CPU must not accelerate GPU, disks, RAM, storage or UPS. A hot NVMe must not accelerate other disks.

## Data flow

```text
raw collectors
    -> raw internal App state (unchanged)
    -> presentation router
         -> decision windows -> local resource profile
         -> continuous numeric values -> publication averaging bucket
         -> discrete/change/event/static -> immediate/change-only path
    -> independent retained MQTT state groups
    -> Home Assistant / Recorder
```

`decision_window` and `average_window` are deliberately different:

- `decision_window`: fixed rolling window used only to choose a resource profile;
- `average_window`: profile-selected publication bucket used to build HA history.

Raw samples are not published as ordinary history points, except an explicit manual Refresh snapshot.

## Publication profile ladder

Default values are policy parameters and must be easy to tune later.

| Profile | Default HA `average_window` | Meaning |
|---|---:|---|
| `critical` | 30 s | maximum useful Recorder detail |
| `high` | 60 s | resource is materially loaded / approaching a limit |
| `normal` | 600 s | ordinary history; tune within 5-10 min after observing data |
| `quiet` | 3600 s | very slowly changing operational telemetry |
| static/inventory | change-only; optional 24 h heartbeat | not normal telemetry |

The presentation layer must never fabricate time resolution. Effective publication cadence cannot be faster than real source collection cadence.

`effective_average_window = max(profile.average_window, source_collection_interval)`

## CPU

CPU publication group contains:

- usage %;
- temperature;
- average frequency;
- throttling state.

Starting selector parameters:

- usage `decision_window`: 60 s;
- usage enter `high`: >=75%;
- usage enter `critical`: >=95%;
- usage high exit: <60%;
- usage critical exit: <85%;
- temperature `decision_window`: 60 s;
- temperature enter `high`: >=80 C;
- temperature enter `critical`: >=90 C;
- temperature high exit: <75 C;
- temperature critical exit: <85 C.

CPU throttling is an immediate critical trigger:

- `cpu_throttling=ON` publishes immediately;
- CPU profile becomes `critical` without waiting for a numeric decision window;
- CPU numeric values published at that boundary use the current publication average, not an isolated raw spike;
- after throttling clears, downgrade is still governed by numeric hysteresis.

## RAM

RAM is independent from CPU. Linux/Proxmox memory commonly sits around 70-90%, so RAM thresholds are intentionally much higher.

Starting selector parameters:

- `decision_window`: 120 s;
- enter `high`: >=92%;
- enter `critical`: >=97%;
- high exit: <88%;
- critical exit: <94%.

Swap may raise the RAM profile if materially used/sustained.

Future admin notifications such as "memory remained excessively full for 30-60 minutes; investigate/clean" are a separate notification policy, not publication profiling.

## Disks

Each physical disk owns its own profile.

Continuous telemetry:

- temperature.

Use the existing disk-health temperature limits as the publication selector source of truth:

- HDD warning/critical: 50/60 C;
- SSD warning/critical: 70/80 C;
- NVMe warning/critical: 75/85 C;
- fallback: 70/85 C.

Recommended `decision_window`: 180 s.

SMART health, wear and SMART counters are change-only/event-oriented and are not averaged.

## GPU

Each GPU owns its own profile. CPU activity must never increase GPU publication frequency.

Selectors:

- GPU temperature;
- transcoding/load where available.

Starting parameters:

- `decision_window`: 60 s;
- temperature enter `high`: >=75 C;
- temperature enter `critical`: >=85 C;
- high exit: <70 C;
- critical exit: <80 C;
- transcoding/load may enter `high` when materially active;
- ordinary transcoding activity alone does not require a `critical` profile.

GPU owner is change-only.

## UPS

UPS owns its own profile and never follows PVE CPU/RAM/GPU/disk load.

Continuous averaged telemetry where supported:

- battery charge;
- runtime;
- UPS load;
- battery/input/output voltage;
- input/output frequency.

Immediate discrete states include:

- availability/status;
- on battery;
- low battery;
- replace battery;
- overload;
- bypass;
- charging/discharging.

Starting semantics:

- on battery -> at least `high` immediately;
- low battery / overload / severe fault -> `critical` immediately;
- continuous selector window approximately 30 s;
- recovery requires hysteresis/stable state.

## Entity classes

### Continuous numeric / averaged

- CPU usage, temperature, frequency;
- RAM usage, swap usage;
- storage usage;
- per-disk temperature;
- per-GPU temperature and numeric transcoding/load;
- fan RPM where graphing is useful;
- UPS charge/runtime/load/voltage/frequency.

### Change-only

- disk health;
- SMART problem state;
- SMART counters/wear when value changes;
- GPU owner;
- VM/LXC status and summaries;
- passthrough ownership/topology;
- UPS capabilities/policy/readiness/config state;
- beeper/test result where stateful.

### Event-only

- boot event / last boot transition;
- previous shutdown;
- shutdown-history changes;
- per-guest shutdown result/timing;
- UPS scan result;
- UPS test completion/history change.

### Static/inventory

- system/board/CPU/memory inventory;
- kernel/Proxmox version;
- primary IP where treated as inventory;
- disk identity;
- UPS identity/nominal specifications;
- static capability thresholds/delays.

Static data is never averaged.

### Controls

- Refresh;
- UPS scan;
- UPS test controls/schedules;
- raw collector interval controls.

Legacy `*_publish_delta` controls belong to the old delta publication policy and must be removed/tombstoned during migration.

## Manual Refresh

Refresh is an explicit operator request for current truth.

On Refresh:

1. run all available collectors immediately;
2. publish all supported groups immediately;
3. numeric state may use the freshly collected current value for this manual snapshot;
4. do not reset rolling decision windows;
5. do not reset normal publication accumulators;
6. do not change a profile from one isolated raw sample unless a discrete critical condition exists;
7. update `last_publication` with reason `manual_refresh`.

## Profile transitions

On transition to a more detailed profile:

- publish immediately at the transition boundary;
- numeric telemetry uses the current average bucket/decision average, not a raw spike;
- begin a fresh bucket using the shorter `average_window`.

On downgrade:

- require hysteresis/stable recovery;
- close the short bucket cleanly;
- begin a longer bucket.

At ordinary bucket close, unchanged rounded state may be suppressed. `average_window` is the maximum desired temporal resolution, not an obligation to generate meaningless Recorder rows.

## Independent MQTT groups

The existing monolithic PVE and UPS state payloads must no longer be the publication unit.

Target conceptual groups:

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
.../<instance>/state/collector/<name>
.../<instance>/state/diagnostics
.../<instance>/ups/state/telemetry
.../<instance>/ups/state/status
.../<instance>/ups/state/config
.../<instance>/ups/state/tests
.../<instance>/ups/state/diagnostics
```

Invariant: publishing one group must not cause unrelated HA entities to receive a state message.

Discovery should keep entity IDs/unique IDs stable wherever practical and point each entity to the smallest appropriate retained state group.

## Recorder-safe attributes

Broad Recorder globs stay simple. Safety comes from entity design.

For continuous sensors:

- state = averaged numeric value;
- attributes = stable identification/UI metadata only;
- do not attach high-frequency raw numbers as attributes.

Examples to remove from continuous entity attributes:

- RAM `used_gib` changing on every sample;
- storage `used_gib`/volatile status;
- duplicated raw telemetry.

If a volatile numeric value deserves history, expose it as a separately averaged entity rather than as a volatile attribute.

Event/change-only/static entities may carry richer compact attributes when those attributes belong to the event/state.

## Diagnostics

Add:

- `sensor.dh_pve_app_profile`;
- `sensor.dh_pve_last_publication`.

`app_profile` state is the highest active resource level (`normal`, `high`, `critical`; `quiet` optional). Attributes identify active resource profiles/reason but must not contain continuously changing decision averages.

`last_publication` state is the timestamp of the last successful state-group MQTT publication. Compact attributes may include group, reason and effective profile.

## Home Assistant package

Recorder may keep broad includes such as:

```text
sensor.dh_pve_*
binary_sensor.dh_pve_*
number.dh_pve_ups_*
time.dh_pve_ups_*
```

Profile thresholds/windows live in App policy/configuration, not HA helpers.

Audit the existing six HA `input_number` thresholds. If they have no independent notification purpose, remove them. If retained for notifications, clearly separate them from publication/profile policy.

## Migration invariants

Do not redesign:

- raw collectors;
- UPS shutdown ownership/safety policy;
- shutdown history semantics;
- dynamic discovery object identity;
- default raw collector intervals.

Removed legacy discovery components must receive MQTT Discovery tombstones.

## Required tests

At minimum:

1. CPU usage raises only CPU detail.
2. CPU temperature raises only CPU detail.
3. CPU throttling immediately sets CPU `critical`.
4. CPU critical does not accelerate GPU/RAM/disks/UPS.
5. GPU activity does not accelerate CPU/unrelated GPUs.
6. one hot disk accelerates only that disk.
7. ordinary 70-90% RAM does not trigger high profile.
8. RAM high/critical hysteresis behaves as configured.
9. UPS discrete fault/battery states publish immediately.
10. normal numeric HA states are averaged.
11. critical HA bucket defaults to 30 s, not 15 s.
12. profile transitions do not publish raw numeric spikes.
13. publication cannot outrun source collector cadence.
14. one group publication cannot update unrelated entities.
15. continuous sensor attributes contain no volatile raw numeric fields.
16. unchanged averaged state can be suppressed.
17. Refresh publishes all current groups immediately without resetting decision history.
18. `app_profile` reports the maximum active level/cause only on meaningful transitions.
19. `last_publication` records successful group publication.
20. dynamic discovery/tombstones still work.
21. existing shutdown/UPS safety tests remain green.
22. broad Recorder package remains simple.

## Tuning policy

Initial thresholds/windows are intentionally parameters. After real Recorder history is collected, tuning should require changing policy values only. The presentation/router/discovery architecture must not need rewriting for normal threshold/window tuning.
