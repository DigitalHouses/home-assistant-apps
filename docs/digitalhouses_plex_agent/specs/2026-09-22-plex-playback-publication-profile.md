# DigitalHouses Plex Agent — PLAYBACK publication profile

**Date:** 2026-09-22  
**Status:** Approved architecture / implementation-ready  
**Product:** `digitalhouses_plex_agent`

## 1. Goal

During active Plex playback, CPU and GPU history must update often enough to make playback and transcoding behavior understandable from Home Assistant without increasing the Linux acquisition cadence.

The existing NORMAL and DETAIL publication windows remain useful outside playback, but the current five-minute DETAIL window is too coarse for active playback.

## 2. Profiles

Plex Agent uses three Recorder-facing publication profiles:

| Profile | Condition | CPU/GPU publication window |
| --- | --- | ---: |
| `NORMAL` | idle / no special workload | 15 minutes |
| `DETAIL` | scanner activity or sustained high CPU without playback | 5 minutes |
| `PLAYBACK` | active playback or running Plex Transcoder | 30 seconds |

The fixed process and GPU acquisition cadence remains 10 seconds by default.

`PLAYBACK` is a presentation/publication profile only. It must not speed up the collector loop.

## 3. PLAYBACK entry

Enter `PLAYBACK` immediately when either condition is true:

- Plex API reports `playback_active = true`;
- local process collection reports `transcoder_running = true`.

When both are true, `transcoder_running` may remain the diagnostic reason because it is the more specific workload signal.

A transition into `PLAYBACK` publishes CPU and GPU groups immediately instead of waiting for the first 30-second window.

Playback semantic changes continue to publish immediately.

## 4. PLAYBACK steady state

While `PLAYBACK` remains active:

- process/GPU samples continue to be acquired at the normal 10-second source cadence;
- CPU and GPU continuous values are accumulated into a 30-second window;
- the published value is the existing window average, preserving the established Recorder-facing aggregation model;
- unchanged values may still be suppressed by the existing publication primitive after the window completes.

This normally produces three acquired samples per 30-second publication window.

## 5. Exit from PLAYBACK

When neither playback nor transcoder is active, the profile is recalculated immediately:

- scanner running -> `DETAIL`;
- sustained CPU above the existing high-CPU threshold -> `DETAIL`;
- otherwise -> `NORMAL`.

A profile transition out of `PLAYBACK` publishes CPU and GPU immediately so Home Assistant does not retain a stale playback-period value until the next long window.

## 6. Semantic publication

The existing event-like behavior is unchanged:

- playback start/stop -> immediate playback group update;
- playback session/media/client/mode decision change -> immediate playback group update;
- hardware-transcode state change -> immediate playback group update;
- transcoder/scanner activity change -> immediate activity group update;
- startup, reconnect, force and manual refresh behavior remain unchanged.

The new 30-second rule applies to continuous CPU/GPU presentation only.

## 7. Diagnostics

`sensor.dh_plex_publication_profile` exposes `playback` while the PLAYBACK profile is active.

Profile diagnostics continue to expose the reason, for example:

- `playback_active`;
- `transcoder_running`;
- `scanner_running`;
- `high_cpu`;
- `recovered`.

CPU and GPU use the same selected profile.

## 8. Compatibility

No service names, paths, MQTT topics, device IDs, Home Assistant entity IDs, collector cadence, or GPU helper privilege model change.

This is a PATCH-level behavior change and is targeted for DigitalHouses Plex Agent `0.4.1`.

## 9. Test requirements

Tests must verify:

- `PublicationProfile.PLAYBACK` exists;
- default profile windows are NORMAL 900 s, DETAIL 300 s, PLAYBACK 30 s;
- playback selects PLAYBACK;
- transcoder activity selects PLAYBACK;
- scanner without playback selects DETAIL;
- high CPU without playback selects DETAIL;
- entering PLAYBACK publishes CPU/GPU immediately;
- steady PLAYBACK does not publish before 30 seconds;
- steady PLAYBACK publishes CPU/GPU at 30 seconds using the accumulated average;
- leaving PLAYBACK publishes CPU/GPU immediately and selects the correct next profile;
- source acquisition interval remains unchanged;
- Plex CI actually executes pytest-style contract tests.
