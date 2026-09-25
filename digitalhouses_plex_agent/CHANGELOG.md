# Changelog

## Unreleased

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
