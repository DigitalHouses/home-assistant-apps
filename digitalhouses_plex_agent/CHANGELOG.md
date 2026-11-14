# Changelog

## Unreleased

- Prepare DH Sync Discovery Contract v1 for the next approved Plex Agent release:
  publish the canonical product/source/running version to retained QoS1
  DigitalHouses/Global/digitalhouses_plex_agent[/<instance_id>]/sync
  on MQTT connect/reconnect through existing Paho; preserve all existing
  MQTT/HA identities, availability/LWT and reconnect/backoff behavior.
  No executable release is created by this source-only PR.

## 0.8.17

- Add dh-plex-agent update: latest published stable Plex release, existing independent systemd update worker, backup, verification and rollback; no MQTT dependency or Plex Server restart. Preserve installed INI, reject concurrent updates and print UP_TO_DATE when current.
- Detect missing ensurepip/python3-venv during Debian 13 preflight, and recover a half-created virtualenv missing pip.
- Measure the entire Plex Agent process CPU with the PVE Agent hysteresis: 10-second sampling, >80% for 300 seconds confirms overload and <40% for 120 seconds clears it; values use one-core normalization, can exceed 100%, and long gaps reset confirmation.
- Expose sensor.dh_plex_agent_process_cpu_usage, binary_sensor.dh_plex_agent_cpu_overload with HA problem device_class and live event.dh_plex_agent_cpu_diagnostic start/clear transitions. The existing agent card flags sustained CPU overload when no GPU fault takes priority.
- Keep local CPU sampling while MQTT_PAUSED; resume only latest MQTT state, without stale event replay. Preserve prior Plex workload/GPU sensors, GPU diagnostic event identity, Recorder and approved dashboard.

- Synchronize the operator-supplied current Plex Lovelace Dashboard as the canonical example, preserving its exact YAML, path `dh-plex-agent`, card positions, responsive grid settings and diagnostic layout. Update UI regression expectations without altering Linux agent functionality.

## 0.8.16

- Add a compact full-width Mushroom card directly under the Plex heading to display the Linux media server hostname and IPv4 from existing MQTT host sensors. Show clear unavailable fallbacks instead of raw unknown states. No new entities or backend changes.
- Keep the approved playback/transcoding layout, background tasks, CPU/GPU graphs and compact System/Media bars unchanged. Manually configured Lovelace panels require updating the dashboard YAML.

## 0.8.15

- Restore compact Plex System/Media storage progress cards matching the approved DH PVE Agent layout: progress bar to the right, not in a dedicated row below the text.
- Show concise `Занято used / total` in GiB or TiB under short `System` and `Media` labels, with used percentage in the title. Keep automatic deduplication of actual filesystem mounts, exclude stale/unavailable sensors, and preserve existing entities and all other Dashboard sections.
- Dashboard YAML only: users with manually configured Lovelace panels must apply the updated card.

## 0.8.14

- Make the Plex Work Mushroom card span the entire first dashboard column (`grid_options.columns: 12`) and show the actual Plex API playback session mode: Direct Play, Direct Stream or Transcoding. Concurrent different modes are listed without guessing; no session falls back to general playback, and idle/background states remain unchanged.
- Keep separate Video and Audio Transcoding cards side by side, and preserve all existing sensor IDs, background-task widths, graphs and media capacity bars. Dashboard YAML only; no service/agent installation needed.

## 0.8.13

- Split the Dashboard transcoding status into independent Video Transcoding and Audio Transcoding Mushroom cards. Each reads its existing Plex API binary sensor, shows Active/Idle or unavailable, and handles audio-only Direct Stream.
- Keep the Work tile generic (Playback, Audio Analysis, other Background, Idle) without conflating stream transcoding or Linux process counts. Preserve GPU, System/Media storage bars and background card width.
- Dashboard YAML only; manually configured Lovelace dashboards must be updated separately.

## 0.8.12

- Fix the Plex Work Mushroom tile to derive active playback/transcoding exclusively from Plex API session sensors rather than a Linux Transcoder process that may remain after a viewer disconnects. Show background audio analysis or other background jobs independently and fall back to Waiting when Plex has no session/task. Handle unavailable Plex API without falsely reporting idle.
- Place System/Media progress bars in a dedicated row **below** full-width free-space text using the supported entity-progress-card-template `bar_position: below` setting. Preserve sensor IDs, backend collectors, MQTT Discovery, CPU/GPU graphs and all other dashboard cards.
- Dashboard-only change: Home Assistant Lovelace YAML is applied manually; installing the updated agent alone will not replace the dashboard.

## 0.8.11

- Persist acknowledged Device Discovery component manifests atomically across restarts. Reconcile confirmed library and mount inventories with platform-only removal tombstones followed by the final payload; selectively clear only removed, unshared agent state topics.
- Publish Discovery with retained QoS1 and bounded PUBACK waits, reusing a single pending receipt across reconnects. Preserve QoS0 metrics and the existing GPU event transport.
- Replace early skeleton republishing with authoritative synchronization after collection on startup, HA birth and reconnect; repair broker config loss every 1800 seconds online. Retry failures at 10-second cadence without pruning during API outages or unconfirmed inventory.
- Preserve MQTT identities, System / Media bars, Audio Analysis and MQTT_PAUSED low CPU behavior. Local source changes only; no deployment or release publication.

## 0.8.10

- Add the Linux system root filesystem to the existing media capacity sensors, so the dashboard shows both independent VM system and media storage. Never use root filesystem statistics to disguise an unmounted media library.
- Compact storage progress card titles to System / Media and short free-versus-total capacity labels; ignore obsolete unavailable storage sensors left in Home Assistant by old Discovery revisions. Existing MQTT and library identities are preserved.

## 0.8.9

- Fix library storage capacity detection when the unprivileged Plex Agent cannot traverse protected media-library folders. Permission denial on child directory metadata no longer masks a healthy mounted filesystem; the agent checks the actual mount and reads statvfs without gaining access to media files.
- Keep missing/unmounted media locations unavailable, preserve existing storage entity IDs and 0.8.8 Audio Analysis / Playback behavior. No Plex/Jellyfin/ZFS changes or new permissions.

## 0.8.8

- Recognize Plex Transcoder audio loudness analysis from audio loudnorm filters and null output, separately from playback transcoding. Keep legacy transcoder process diagnostics and API playback sensors unchanged.
- Publish audio-analysis running state and a bounded, PID-ordered background process list (scanners and audio analysis only, filenames without paths).
- Replace idle background task rows with one Mushroom card visible only while background processes run. Preserve v0.8.7 library storage progress bars.
- Source changes only; no deployment or release publication performed.

## 0.8.7

- Add one library filesystem capacity sensor and dashboard progress bar per actual media mount, shared by libraries on the same filesystem.
- Collect with statvfs at startup/reconnect, library changes, manual refresh and every 60 seconds while MQTT is online. Use df-style used plus user-available capacity; missing mounts and unknown capacity remain unavailable.
- Preserve existing CPU charts, playback classification, MQTT identities and Recorder configuration. Source changes only; no deployment or published-release acceptance is implied.

## 0.8.6

- Fix the MQTT-offline overdue-heartbeat busy loop. Suspend foreground process, GPU and Plex API collection in `MQTT_PAUSED`, keep the existing systemd service alive, and collect a fresh snapshot when the broker reconnects.
- Bound MQTT reconnects (60-second delay, 5-second connection timeout) and pending QoS 1 messages; never enqueue new publications while disconnected. Keep GPU diagnostic events until broker PUBACK, with a durable 32-event outbox that drops the oldest event on overflow.
- Add the root/admin native `/usr/local/bin/dh-plex-agent` CLI: offline-capable status, restart, help and atomic batch configuration for all 21 native settings, with safe password input and idempotent service restarts.
- Write a compact root quick reference during install/update; support unattended first installation with a preprovisioned native INI and refuse to start unconfigured.
- Add Linux hostname and route-selected local IPv4 diagnostic sensors to the existing MQTT Discovery device, plus local atomic runtime status without secrets.
- Preserve installed runtime identity, existing MQTT/HA identifiers, updater and separate GPU helper. No production deployment or published-release acceptance is implied by this source change.

## 0.8.5

- Add the Home Assistant MQTT event entity `event.dh_plex_agent_gpu_diagnostic` for confirmed Intel GPU availability and PCI kernel-driver binding transitions.
- Publish `gpu_unavailable`, `gpu_restored`, `gpu_driver_unbound`, `gpu_driver_restored` and `gpu_driver_changed` events with PVE-compatible schema v2, severity, timestamp, PCI address, driver and previous/current state.
- Debounce over two consecutive polls, coalesce simultaneous driver and GPU failures, and suppress repeats during continuous faults or normal agent restarts.
- Persist confirmed GPU health and a pending-event outbox through temporary MQTT outages; publish events QoS 1 without MQTT retain. No built-in notifications or HAOS recipient changes.
- Keep the existing GPU metrics, main problem card, API, MQTT identities and agent resource profile unchanged.

## 0.8.4

- Add a standalone Intel GPU diagnostic card showing the PCI-bound driver (for example i915) separately from whether GPU telemetry and hardware engines actually work. A bound driver no longer falsely implies a healthy GPU.
- Expose `sensor.dh_plex_agent_gpu_driver_status` with binding state and driver name via the existing GPU MQTT group, preserving the existing `sensor.dh_plex_agent_gpu_status` telemetry.
- Show persistent `problem` on the unified Plex Agent card when an expected Intel GPU is unavailable, with the reason. Foreground update/refresh/restart controls continue to take priority; automatically recover to idle when GPU telemetry works.
- Machines without Intel GPU do not trigger the problem state. No GPU driver, VM, video playback, or Recorder settings are changed.
- Add tests for a bound-but-failed GPU, missing driver, recovery, card lifecycle, grouped GPU MQTT publication, and canonical Home Assistant UI examples.

## 0.8.3

- Fix the 0.8.2 regression where MQTT Discovery exposed separate Audio/Video Transcoding sensors but the grouped playback publisher omitted their values, leaving Home Assistant tiles blank.
- Forward audio/video stream mode, ON/OFF flags and per-session UI details through the existing playback MQTT group, and include them in change detection so updates and Idle transitions are published reliably.
- Add a regression test covering the full Plex API → publication router → MQTT bridge contract, including audio-only transcoding, video transcoding and idle.
- No changes to entity IDs, Recorder policy, other GPU telemetry or Media Server configuration.

## 0.8.2

- Add separate audio and video transcoding status sensors for Home Assistant UI, using Plex per-stream decisions and compact per-session details; distinguish Direct Play, Direct Stream, and Transcoding.
- Add attribute-free audio/video transcoding binary sensors (ON/OFF) for clean Recorder history. Preserve unavailable state on Plex API failure instead of reporting false OFF.
- Correctly classify audio-only transcodes without marking the video stream as transcoding, count subtitle burn-in as video transcoding, and aggregate across concurrent sessions.
- Provide an optional HAOS Recorder package example that records only the two binary flags and excludes the rich UI sensors; merge it with the site's existing Recorder configuration.
- Keep existing MQTT identifiers, dashboards, playback summaries, GPU metrics, and installation paths unchanged. No migration required.

## 0.8.1

- Restore GPU telemetry on Debian 13 and recent `intel_gpu_top` versions by parsing streamed bracketed JSON, including incomplete trailing samples.
- Support modern GPU engine names (`Video`, `Render/3D`, `VideoEnhance`) alongside the legacy `/0` names, without confusing Video with Video Enhance.

## 0.8.0

- Add the unified DigitalHouses Agent control card, mirroring the production PVE Agent UI with one-second elapsed time (no tenths), app-owned operation states and collection freshness.
- Add Refresh, Release Check, verified Update and Restart commands, with retained MQTT control commands rejected and no extra Home Assistant helpers or devices.
- Introduce protected, independent root-only Plex Agent updater, immutable release verification, backups, rollback and interrupted-update recovery; Plex Media Server is never restarted.
- Persist operation state across agent restarts; only report restart/update success after the new process and independent update worker confirm it.

## 0.7.2

- Self-heal a rotated Plex `.LocalAdminToken`: on local API HTTP 401 the unprivileged agent writes a rate-limited request marker; a dedicated systemd path-activated, root-owned one-shot helper validates the original token and atomically updates the protected agent copy. The next poll recovers without restarting the agent or Plex.
- Do not replace a working token with an unavailable or unauthorized candidate; never expose token values in logs, MQTT, or command output. Keep the main service unprivileged and install/rollback the narrow watcher automatically.

## 0.7.1

- Fix the first canonical HA/MQTT identity migration from the historical default topic prefix: preserve the regular-expression end-of-line anchor literally so Bash cannot expand it as a positional-argument expression and corrupt the sed command.
- Add an installer regression test that executes the exact topic-prefix rewrite block against a legacy configuration and verifies the canonical `DigitalHouses/Global/digitalhouses_plex_agent` result.

## 0.7.0

- Complete the deferred Home Assistant/MQTT identity migration to canonical product identity: MQTT base `DigitalHouses/Global/digitalhouses_plex_agent`, Discovery device ID `digitalhouses_plex_agent_plex`, and `dh_plex_agent_*` entity IDs.
- Add controlled retained-MQTT/Discovery cleanup for the historical `DigitalHouses/Global/plex_monitoring` / `digitalhouses_plex_monitoring_plex` contract; custom MQTT namespaces are preserved and only their legacy Discovery identity is tombstoned.
- Add opt-in protocol-v1 product telemetry for `digitalhouses_plex_agent`, default OFF, with persistent UUID/token identity, released-build gating, 24-hour jittered cadence, one-hour failure backoff, isolated background delivery, and authenticated deletion.
- Store telemetry identity outside the source tree under `/var/lib/digitalhouses/digitalhouses_plex_agent/telemetry.json`; preserve identity across restart and update.
- Enforce required Contract Data semantics for Version, Started-at, and Plex API status; remove synthetic Discovery fallbacks for required diagnostics and add negative regression tests.
- Keep production installation release-tag-only and retain exact source tag + resolved commit SHA in `BUILD_INFO`.
- Canonicalize the public dashboard/config examples and product validator, while retaining legacy names only in migration code and historical release documentation.

## 0.6.0

- Migrate the installed Linux runtime identity from `digitalhouses_plex_monitoring` to canonical `digitalhouses_plex_agent`: service/user/group, `/opt`, `/etc`, `/var/lib`, config file and GPU helper service.
- Add a controlled copy-first migration for existing installations with a root-only tar backup, idempotent migration marker and preservation of config, Plex token, playback-session state and GPU helper state.
- Rewrite only the historical default Plex token path in the copied config; user MQTT settings and other explicit configuration remain unchanged.
- Automatically restore the previous legacy service state if the canonical main service fails its first start.
- Retain the legacy config/state trees after a successful first migration as an immediate rollback snapshot.
- Keep MQTT base `DigitalHouses/Global/plex_monitoring`, Discovery device ID `digitalhouses_plex_monitoring_plex` and all existing `dh_plex_*` Home Assistant entities unchanged; HA identity migration remains a separate release.

## 0.5.0

- Normalize Plex, Scanner, and Transcoder CPU sensors to 0-100% of the complete logical CPU capacity available to the machine instead of Linux per-core `top` semantics.
- Remove the six public 1-minute CPU average/maximum entities and their MQTT payload fields; Home Assistant keeps the historical time series of the three primary CPU sensors.
- Keep adaptive Recorder-facing publication unchanged: 10-second acquisition with 30-second PLAYBACK, 5-minute DETAIL, and 15-minute NORMAL presentation windows.
- Add diagnostic `sensor.dh_plex_agent_started_at` as a timestamp while retaining the low-level `sensor.dh_plex_agent_uptime` compatibility entity.
- Add `sensor.dh_plex_playback_started_at` for the earliest currently active Plex playback session.
- Persist internal playback-session start timestamps under `/var/lib/digitalhouses_plex_monitoring/` so an agent restart does not reset an ongoing session timestamp.
- Update the example dashboard and repository compatibility contract for the simplified CPU model and timestamp sensors.

## 0.4.1

- Add the `PLAYBACK` publication profile for active playback or Plex Transcoder activity.
- Publish averaged CPU and GPU telemetry every 30 seconds during `PLAYBACK` while keeping the 10-second acquisition cadence unchanged.
- Keep `DETAIL` at 5 minutes for scanner/high-CPU activity without playback and `NORMAL` at 15 minutes for idle operation.
- Publish CPU/GPU immediately when entering or leaving `PLAYBACK`; semantic playback/activity changes remain immediate.
- Run the Plex test suite with pytest so the existing pytest-style contract tests are executed by CI.

## 0.4.0

- Add standalone Intel GPU telemetry from the Plex Linux host/VM: Video, Render/3D, Video Enhance, GPU frequency, RC6 and real GPU temperature when the kernel exposes it.
- Add `binary_sensor.dh_plex_hardware_transcode_active` from Plex session semantics and keep it distinct from measured GPU utilization.
- Add `sensor.dh_plex_last_boot` for host/VM uptime while retaining `sensor.dh_plex_agent_uptime` as process diagnostics.
- Add the retained `gpu` MQTT state group using the existing NORMAL/DETAIL adaptive publication model.
- Update the Plex dashboard with server uptime and GPU/transcoding telemetry without any DH PVE dependency.
- Prepare the installer for optional `intel-gpu-tools` and existing render/video group access on supported Debian/Ubuntu Intel GPU hosts.
- Isolate the i915 PMU privilege in `digitalhouses_plex_gpu_helper.service`: the main Plex Agent remains unprivileged, while the helper alone receives `CAP_SYS_ADMIN` and publishes a timestamped local GPU snapshot.

## 0.3.0

- Align Plex with the DH PVE Linux Agent runtime model: fixed collection cadence, semantic grouped MQTT state, adaptive NORMAL/DETAIL presentation, retained cache republish, and per-group retry.
- Publish activity, playback and library semantic changes immediately while averaging continuous CPU telemetry over the common 15-minute NORMAL / 5-minute DETAIL windows.
- Add diagnostic `sensor.dh_plex_agent_version`, `sensor.dh_plex_agent_uptime`, `sensor.dh_plex_publication_profile`, and `sensor.dh_plex_last_publication`.
- Remove the commit/build sensor from Home Assistant UI; release provenance remains available in on-host `BUILD_INFO` and logs.
- Preserve existing service/path, MQTT base namespace, device ID, and existing workload/playback/library entity IDs.

## 0.2.3

- Align production install/update with the repository Release Policy: the normal deployment source is the canonical `digitalhouses_plex_agent-v<version>` release tag, never `main`.
- Require an explicit source ref and reject non-release refs by default; retain an explicit development/testing override without changing production behavior.
- Verify that a canonical release tag contains the matching product `VERSION` before installation and continue recording version, source tag/ref, and exact commit SHA in `BUILD_INFO`.
- Preserve all existing runtime identities, including the `digitalhouses_plex_monitoring` service/path names, MQTT namespace/device identifiers, and Home Assistant entity IDs.

## 0.2.2

- Keep Plex playback session identifiers internal for change detection and omit them from MQTT/Home Assistant playback attributes.

## 0.2.1

- Replace the systemd `LoadCredential=` token handoff with a protected `/etc/digitalhouses_plex_monitoring/plex_local_admin_token` copy.
- Keep the service unprivileged and preserve the original Plex `.LocalAdminToken` permissions.
- Remove the legacy 0.2.0 credential drop-in automatically during update.

## 0.2.0

- Add local Plex API playback monitoring without requiring the Home Assistant Plex integration.
- Read Plex `.LocalAdminToken` through a systemd credential instead of storing a Plex account token in app configuration.
- Add playback count, session details, and playback-active binary sensors.
- Expose mandatory playback `content_type` values `video` and `audio`, including dedicated video/audio playback binary sensors.
- Detect Direct Play, Direct Stream, and Transcode decisions from Plex session data.
- Expose playback user, client, media, codec, bandwidth, and hardware-transcode context.
- Add Plex library discovery and real movie/show/season/episode/artist/album/track counters.
- Add stable per-library entities based on Plex section IDs.
- Refresh library counters at startup, on manual refresh, after scanner completion, and periodically.
- Keep the Plex API collector independent from the existing Linux `/proc` workload collector.

## 0.1.3

- Detect Plex Transcoder input media from `-i` and ignore ffmpeg output formats such as `-f dash`.
- Remove opaque Plex item and section IDs from `current_item`.
- Support multiple simultaneous active media items.
- Add active-item attributes and `sensor.dh_plex_transcoder_count`.
- Publish immediately when the active media workload changes.

## 0.1.2

- Detect Plex Server, Scanner and Transcoder reliably when Linux truncates process names or Plex splits the executable name across argv.
- Use the same process-role detection for activity classification and CPU grouping.

## 0.1.1

- Use flat default MQTT namespace `DigitalHouses/Global/plex_monitoring`.
- Use `plex` as the non-interactive default instance ID and hostname as instance name.
- Fix virtualenv permissions for the unprivileged systemd service.
- Update `last_refresh` only after a successful manual refresh.

## 0.1.0

- Initial DigitalHouses Plex Monitoring Linux agent.
