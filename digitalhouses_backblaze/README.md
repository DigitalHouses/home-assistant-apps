# DigitalHouses Backblaze App

Home Assistant App for monitoring Backblaze B2 storage usage through MQTT Discovery.

## Status

Initial implementation. The App is currently `experimental`.

## What it reports

One Home Assistant MQTT device exposes:

- total completed-file storage across all buckets visible to the configured key;
- bucket count;
- per-bucket storage;
- per-bucket current file count;
- per-bucket stored version count;
- Backblaze API connectivity;
- last successful/attempted update;
- App version;
- App process started-at timestamp;
- manual refresh button.

Storage is calculated from `b2_list_file_versions` and includes all completed `upload` versions, including old versions that still occupy B2 storage. Hide markers do not contribute bytes.

Unfinished multipart uploads are not included in v0.1.0.

## Backblaze key

Use a dedicated Backblaze Application Key with only:

- `listBuckets`
- `listFiles`

The App uses B2 Native API v4.

For an unrestricted account key, all accessible buckets are listed. B2 v4 restricted or multi-bucket keys are also supported; only buckets allowed by the key are reported.

## Home Assistant entities

Stable common entities:

- `sensor.dh_backblaze_storage_used`
- `sensor.dh_backblaze_bucket_count`
- `sensor.dh_backblaze_last_update`
- `binary_sensor.dh_backblaze_api`
- `sensor.dh_backblaze_app_version`
- `sensor.dh_backblaze_app_started_at`
- `button.dh_backblaze_refresh`

Bucket entity IDs are derived from bucket names, for example:

- `sensor.dh_backblaze_ha_backups_storage_used`
- `sensor.dh_backblaze_ha_backups_files`
- `sensor.dh_backblaze_ha_backups_versions`

## Configuration

```yaml
application_key_id: ""
application_key: ""
refresh_interval_hours: 6
telemetry_enabled: false
log_level: info
```

A full scan is run at startup, every configured interval, and when the Home Assistant Refresh button is pressed.

## Telemetry

DigitalHouses usage telemetry is optional and disabled by default. When enabled, it follows the repository-wide Product Telemetry Policy and sends only the shared protocol fields. Backblaze credentials, bucket names, bucket IDs, storage values, file names, and account data are never part of DigitalHouses telemetry.

## Release identity

Repository directory / Home Assistant slug:

```text
digitalhouses_backblaze
```

Public release identifier:

```text
digitalhouses_backblaze_app
```

Canonical release tags use:

```text
digitalhouses_backblaze_app-v<version>
```

The App version in `config.yaml` is the release version source of truth.
