# Plex Agent 0.5.0 — CPU semantics and runtime timestamps

Status: approved implementation design.

## Scope

This release deliberately changes the public CPU metric semantics and therefore uses
version 0.5.0.

### CPU

The public Plex CPU sensors represent the share of the complete logical CPU capacity
available to the Plex VM/host.

Formula:

```text
normalized_percent = summed Linux process CPU percent / logical_cpu_count
```

The published range is clamped to 0..100%.

Keep only:

```text
sensor.dh_plex_cpu
sensor.dh_plex_scanner_cpu
sensor.dh_plex_transcoder_cpu
```

Remove the six public `*_avg` and `*_max` sensors from MQTT Discovery, grouped
MQTT payloads, the example dashboard, tests, and repository compatibility validation.

The existing adaptive publication model remains unchanged: acquisition stays at 10 s,
PLAYBACK publishes CPU/GPU on the 30 s window, DETAIL on 5 min, NORMAL on 15 min.
The adaptive group may average source samples inside its publication bucket.

`high_load_threshold = 80` now means 80% of the whole machine CPU capacity.

### Agent start timestamp

Add:

```text
sensor.dh_plex_agent_started_at
```

It is a diagnostic Home Assistant timestamp generated once at process start.

Keep `sensor.dh_plex_agent_uptime` for compatibility and low-level diagnostics, but
use `agent_started_at` in the example dashboard.

### Playback start timestamp

Add:

```text
sensor.dh_plex_playback_started_at
```

It is a Home Assistant timestamp and is available only while one or more Plex playback
sessions are active.

Semantics:

- track the first-observed start time per internal Plex playback session identity;
- expose the earliest start time among currently active sessions;
- when no playback session is active, publish no timestamp;
- keep internal Plex session IDs out of MQTT/Home Assistant payloads;
- persist the session-start map under
  `/var/lib/digitalhouses_plex_monitoring/` so a Plex Agent restart does not reset
  the timestamp for a session that is still active;
- reconcile persisted entries against the current successful `/status/sessions`
  response and discard entries for sessions that are no longer active;
- Plex API failure must not fabricate a new start time.

This is a monitoring timestamp, not media position. Pause/resume within the same active
Plex session keeps the same start timestamp.

## Compatibility

The CPU semantic change and removal of public avg/max entities are intentional
0.5.0 compatibility changes. Stable service names, MQTT base namespace, device ID,
remaining entity IDs, Plex token handling, GPU helper isolation, and release delivery
contract remain unchanged.

## Tests

Required regression coverage:

- 4 logical CPUs: raw 100% process CPU -> public 25%;
- aggregate raw 400% -> public 100%;
- normalization cannot exceed 100%;
- Discovery contains only the three public CPU sensors;
- avg/max entity IDs are absent;
- `agent_started_at` is a timestamp;
- `playback_started_at` is a timestamp;
- playback timestamp appears on first active session and clears when playback ends;
- overlapping sessions expose the earliest active start;
- when the earliest session ends, timestamp advances to the remaining session start;
- persisted session starts survive runtime recreation when the same session remains;
- public playback attributes still contain no session IDs.
