# DigitalHouses Plex Agent — standalone GPU telemetry and server uptime amendment

**Date:** 2026-09-21  
**Status:** Approved architecture / implementation-ready  
**Product:** `digitalhouses_plex_agent`

## 1. Goal

Plex Agent must remain useful when it is the only DigitalHouses agent installed on the Plex host.

A user investigating playback or transcoding must be able to answer, from the Plex device itself:

- how much CPU Plex uses;
- whether Plex is transcoding;
- whether hardware transcoding is active;
- how busy the Intel GPU video/render engines are;
- what the GPU frequency is;
- whether a real GPU temperature sensor is available;
- how long the Plex host/VM has been running.

Plex Agent must not depend on DH PVE for these answers.

## 2. Standalone ownership

`digitalhouses_plex_monitoring` owns Plex-local workload, playback and GPU telemetry available from the Linux guest/host where Plex runs.

No Proxmox API, `qm`, `pct`, or DH PVE MQTT entities are dependencies.

DH PVE may independently expose the same physical GPU from the hypervisor perspective. That does not replace Plex-local observability.

## 3. GPU collector

Initial GPU support targets Intel DRM/i915 systems because the production Plex host uses Alder Lake-N UHD Graphics and `intel_gpu_top` is verified to expose useful engine telemetry inside the Plex VM.

The collector is optional and fail-soft:

- absence of Intel DRM hardware is supported;
- absence of `intel_gpu_top` is supported;
- permission failure is supported;
- collector failure must not mark the Plex process collector or Plex API collector unavailable;
- no metric is fabricated when the kernel does not expose it.

The collector samples `intel_gpu_top -J` and normalizes:

- `video_busy_percent` from `Video/*`;
- `render_busy_percent` from `Render/3D/*`;
- `video_enhance_busy_percent` from `VideoEnhance/*`;
- `frequency_mhz` from the actual GPU frequency;
- `rc6_percent` from the RC6 residency value.

For engines with multiple instances, the collector publishes the maximum busy percentage observed in the accepted sample.

A short initialization sample is ignored; only samples whose reported period is at least 500 ms are accepted.

## 4. GPU temperature

GPU temperature is published only when Linux exposes a hardware temperature sensor attached to the selected Intel DRM/PCI device.

The collector may inspect PCI-bound hwmon nodes.

If no GPU-specific temperature source exists, `temperature_c` remains unavailable.

CPU/SoC temperature must never be relabeled as GPU temperature.

## 5. GPU MQTT group

GPU telemetry is a separate retained semantic group:

```text
DigitalHouses/Global/plex_monitoring/state/gpu
```

The group contains normalized values such as:

```json
{
  "supported": true,
  "available": true,
  "source": "intel_gpu_top",
  "video_busy_percent": 21.1,
  "render_busy_percent": 77.7,
  "video_enhance_busy_percent": 0.0,
  "frequency_mhz": 706.7,
  "rc6_percent": 2.3,
  "temperature_c": null
}
```

GPU collection does not alter the fixed Plex process sampling cadence.

Continuous GPU metrics use the same Recorder-facing NORMAL/DETAIL adaptive windows as Plex CPU:

- NORMAL: 15 minutes;
- DETAIL: 5 minutes.

A profile transition, startup, reconnect and manual Refresh publish the GPU group immediately.

## 6. Home Assistant GPU entities

For default `instance_id = plex`:

```text
sensor.dh_plex_gpu_video
sensor.dh_plex_gpu_render
sensor.dh_plex_gpu_video_enhance
sensor.dh_plex_gpu_frequency
sensor.dh_plex_gpu_temperature
sensor.dh_plex_gpu_rc6
sensor.dh_plex_gpu_status
```

Units:

- video/render/video-enhance/RC6: `%`;
- frequency: `MHz`;
- temperature: `°C`.

GPU temperature may be unavailable on integrated Intel GPUs when the guest kernel exposes no GPU hwmon sensor.

## 7. Hardware-transcode aggregate

Plex API session data remains authoritative for whether Plex reports hardware transcoding.

Add:

```text
binary_sensor.dh_plex_hardware_transcode_active
```

It is ON when at least one current playback session has `hardware_transcode = true`.

This is separate from GPU utilization: the first describes Plex session semantics; the second describes measured hardware activity.

## 8. Plex host/VM uptime

`sensor.dh_plex_agent_uptime` remains a diagnostic process-lifetime sensor and continues to reset when the agent restarts.

Add:

```text
sensor.dh_plex_last_boot
```

Its state is the Linux host/VM boot timestamp derived locally from the operating system.

The default dashboard presents human-readable host uptime from this timestamp using the same presentation convention as DH PVE:

```text
1 д. 18:02
```

Restarting or upgrading Plex Agent must not reset this server uptime.

## 9. Dashboard contract

The Plex dashboard must be self-contained and must not require DH PVE entities.

The primary transcoding/resource view should expose, when available:

```text
Plex CPU
GPU Video
GPU Render
GPU Video Enhance
GPU frequency
GPU temperature
Hardware transcode
```

RC6 and agent uptime remain diagnostic rather than primary operator metrics.

## 10. Installer/runtime permissions

The installer should make Intel GPU telemetry work on supported Debian/Ubuntu Plex hosts without requiring DH PVE.

If Intel DRM hardware is present and `intel_gpu_top` is absent, the installer may install the Debian/Ubuntu `intel-gpu-tools` package.

The service user should be granted existing `render` and/or `video` supplementary groups when needed. No broad root runtime privilege is introduced.

If the platform still denies GPU performance counters, the GPU collector reports unavailable and the rest of Plex Agent continues normally.

## 11. Compatibility

Existing service name, paths, MQTT base namespace, device ID and existing Home Assistant entity IDs remain unchanged.

The new GPU group and entities are additive.

The legacy `sensor.dh_plex_agent_uptime` is not repurposed.

## 12. Required tests

Tests must cover:

- parsing representative `intel_gpu_top -J` stream output;
- ignoring the short startup sample;
- video/render/video-enhance/frequency/RC6 normalization;
- optional hwmon temperature;
- graceful no-tool/no-hardware/permission behavior;
- grouped GPU publication and retry/cache behavior;
- GPU Discovery IDs, units and availability;
- hardware-transcode aggregate;
- server boot timestamp independent of agent uptime;
- dashboard references for GPU metrics and human-readable server uptime;
- installer contract for optional Intel GPU tooling and service-group access.
