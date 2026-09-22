# DigitalHouses Backblaze

DigitalHouses Backblaze is a Home Assistant App for monitoring Backblaze B2 storage usage.

The App authorizes against the Backblaze B2 Native API v4, discovers all buckets visible to the configured application key, scans file versions, and publishes one Home Assistant MQTT device with account totals and per-bucket entities.

## Status

Version 0.1.6 is the current experimental implementation.

## Backblaze key

Create a dedicated Backblaze application key with only these capabilities:

- listBuckets
- listFiles

To report all buckets, the key must be allowed to see all buckets that should be included in the total. The master application key is not required and should not be used.

## Home Assistant entities

Account entities include:

- sensor.dh_backblaze_storage_used
- sensor.dh_backblaze_bucket_count
- sensor.dh_backblaze_files
- sensor.dh_backblaze_versions
- sensor.dh_backblaze_last_update
- binary_sensor.dh_backblaze_api
- button.dh_backblaze_refresh
- sensor.dh_backblaze_app_version
- sensor.dh_backblaze_app_started_at

Every discovered bucket also gets used, files, and versions sensors under the same Home Assistant device.

## Home Assistant package

Reusable Recorder package:

```text
examples/packages/dh_app_backblaze_package.yaml
```

Recommended Home Assistant target:

```text
/config/packages/Global/DH_APP/dh_app_backblaze_package.yaml
```

The package intentionally records only:

- `sensor.dh_backblaze_storage_used` — account Total used;
- `sensor.dh_backblaze_files` — account Total files.

Bucket-level entities remain live but are not recorded by the reusable package.

## Dashboard

Reusable Sections dashboard:

```text
examples/lovelace/dh_app_backblaze_dashboard.yaml
```

The dashboard contains account totals, dynamic bucket cards, diagnostics, manual refresh, and a 10-day daily bar chart for Total used.

The daily chart uses the same aggregation pattern as the DigitalHouses Recorder UI:

```yaml
hours_to_show: 240
group_by: date
aggregate_func: max
show:
  graph: bar
```

Recorder history from `dh_app_backblaze_package.yaml` is required for the chart.

## Refresh model

The App refreshes immediately after start and then every 6 hours by default. The interval is configurable from 1 to 168 hours. Manual refresh is available from Home Assistant.

## Storage semantics

Stored bytes are calculated from content-bearing file versions returned by b2_list_file_versions. This includes retained historical versions and therefore intentionally differs from current-visible-file size.

Version 0.1.0 does not add uploaded parts belonging to unfinished large-file uploads. The displayed value should therefore be treated as completed stored file-version usage, not as a byte-perfect billing meter when unfinished multipart uploads exist.

## DigitalHouses telemetry

Usage telemetry is optional and disabled by default:

```yaml
telemetry_enabled: false
```

When explicitly enabled, the App follows the shared DigitalHouses Telemetry Protocol v1. It sends only:

- protocol schema version;
- telemetry policy version;
- a random per-installation UUID;
- product identifier `digitalhouses_backblaze_app`;
- App version.

Backblaze credentials, account ID, bucket names, bucket IDs, file names, storage values, Home Assistant identity, hostname, LAN/WAN addresses and MQTT configuration are not telemetry payload fields. Country is derived server-side from request network metadata. The DigitalHouses telemetry system does not retain source IP addresses.

The installation identity and token are stored in `/data/telemetry_state.json` and survive restart, upgrade and supported Home Assistant backup/restore.

Use `button.dh_backblaze_delete_telemetry` to request authenticated deletion of this installation's retained telemetry record. Disabling telemetry stops future heartbeats; deletion and disabling are separate operations.

See `docs/standards/PRODUCT_TELEMETRY_POLICY.md` and `docs/standards/TELEMETRY_PROTOCOL_V1.md`.

## Release identity

Repository directory and Home Assistant App slug:

```text
digitalhouses_backblaze
```

Canonical public release identifier:

```text
digitalhouses_backblaze_app
```

The App remains experimental and must not be treated as a production release until the repository's immutable GHCR delivery contract is implemented for it.

## Compatibility

The App follows the DigitalHouses Application Standard and publishes one MQTT Discovery device. GitHub is the source of truth.
