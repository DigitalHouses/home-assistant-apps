# DigitalHouses Plex Monitoring

Native Linux workload monitoring for Plex Media Server with Home Assistant MQTT Device Discovery.

## Purpose

The agent answers a specific historical question:

> What was Plex doing when CPU temperature, VM/LXC CPU, GPU/video load, storage temperature, or thermal throttling changed?

It runs beside Plex in the same VM, LXC, or Debian/Ubuntu Linux host and inspects local Plex processes. No Plex token and no Proxmox API are required.

## Dashboard

![Plex Monitoring dashboard](images/plex-dashboard.png)

## Install / update

From a root shell:

```bash
curl -fsSL https://raw.githubusercontent.com/DigitalHouses/home-assistant-apps/main/digitalhouses_plex_monitoring/install.sh | bash
```

From a sudo-capable user:

```bash
curl -fsSL https://raw.githubusercontent.com/DigitalHouses/home-assistant-apps/main/digitalhouses_plex_monitoring/install.sh | sudo bash
```

Run the same command again to update from `main`. Existing configuration is preserved.

To install another Git ref:

```bash
curl -fsSL https://raw.githubusercontent.com/DigitalHouses/home-assistant-apps/main/digitalhouses_plex_monitoring/install.sh | sudo env DIGITALHOUSES_SOURCE_REF=v0.1.0 bash
```

## Configuration

```text
/etc/digitalhouses_plex_monitoring/digitalhouses_plex_monitoring.conf
```

Default telemetry:

```ini
[general]
instance_id = plex
instance_name = DH Plex
poll_interval_seconds = 10
cpu_window_seconds = 60
log_level = info

[telemetry]
cpu_change_threshold = 5
high_load_threshold = 80
high_load_publish_interval_seconds = 60
```

CPU follows Linux `top` semantics: **100% means one logical CPU**. Values above 100% are valid on a multi-vCPU Plex guest.

## Publication policy

The process namespace is sampled every 10 seconds, but MQTT is not published every 10 seconds.

A full state is published:
- at startup/reconnect/Home Assistant birth;
- on manual Refresh;
- when Plex activity, active media items, or process-role counts change;
- when current total/scanner/transcoder CPU changes by at least 5 percentage points;
- on 0 ↔ non-zero CPU transitions;
- immediately when current total Plex CPU crosses 80% up or down;
- at least once per minute while current total Plex CPU remains >=80%.

`process_count` alone does not trigger a publication. Changes to active media items do trigger publication so Home Assistant history reflects workload transitions.

## Main entities

With default `instance_id = plex`:

```text
sensor.dh_plex_activity
sensor.dh_plex_current_item

binary_sensor.dh_plex_server_running
binary_sensor.dh_plex_scanner_running
binary_sensor.dh_plex_credits_detection
binary_sensor.dh_plex_intro_detection
binary_sensor.dh_plex_thumbnail_generation
binary_sensor.dh_plex_transcoder_running

sensor.dh_plex_cpu
sensor.dh_plex_cpu_avg
sensor.dh_plex_cpu_max
sensor.dh_plex_scanner_cpu
sensor.dh_plex_scanner_cpu_avg
sensor.dh_plex_scanner_cpu_max
sensor.dh_plex_transcoder_cpu
sensor.dh_plex_transcoder_cpu_avg
sensor.dh_plex_transcoder_cpu_max

sensor.dh_plex_scanner_actions
sensor.dh_plex_process_count
sensor.dh_plex_collector_status
sensor.dh_plex_build
sensor.dh_plex_last_refresh
button.dh_plex_refresh
```

`sensor.dh_plex_current_item` exposes attributes intended for dashboards:

- `count` - number of unique active media items;
- `items` - active media basenames;
- `transcoder_count` - number of Plex Transcoder processes;
- `scanner_count` - number of Plex Media Scanner processes.

With multiple active items its state is `N active items`; the full list remains in attributes.

## Activity classification

Known scanner signatures include:
- Credits: `--server-action credits`, `--creditsTempDataPath`, Credits log suffix;
- Intro: `--server-action intro` or `intros`;
- thumbnails/indexing: `--server-action index`, `--index`, `-b`, `--chapter-thumbs-only`.

Unknown Plex Media Scanner work remains visible as generic `scanner` activity and its `--server-action` values remain visible in `sensor.dh_plex_scanner_actions`.

`Plex Transcoder` means a transcoder process exists. It does **not** by itself prove that a user playback session is being transcoded.

## Playback count

The agent deliberately does not duplicate Plex sessions. Use the native Home Assistant Plex integration for viewer count. A dashboard can correlate that viewer count with the workload entities above.

## Operations

```bash
systemctl status digitalhouses_plex_monitoring
journalctl -u digitalhouses_plex_monitoring -f
```

## Filesystem

```text
/opt/digitalhouses/digitalhouses_plex_monitoring/
/etc/digitalhouses_plex_monitoring/digitalhouses_plex_monitoring.conf
/var/lib/digitalhouses_plex_monitoring/
journald
```
