# DigitalHouses Backblaze

DigitalHouses Backblaze is a Home Assistant App for monitoring Backblaze B2 storage usage.

The App authorizes against the Backblaze B2 Native API v4, discovers all buckets visible to the configured application key, scans file versions, and publishes one Home Assistant MQTT device with account totals and per-bucket entities.

## Status

Version 0.1.0 is the initial implementation and is marked experimental until it is validated against a production Backblaze account.

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

## Refresh model

The App refreshes immediately after start and then every 6 hours by default. The interval is configurable from 1 to 168 hours. Manual refresh is available from Home Assistant.

## Storage semantics

Stored bytes are calculated from content-bearing file versions returned by b2_list_file_versions. This includes retained historical versions and therefore intentionally differs from current-visible-file size.

Version 0.1.0 does not add uploaded parts belonging to unfinished large-file uploads. The displayed value should therefore be treated as completed stored file-version usage, not as a byte-perfect billing meter when unfinished multipart uploads exist.

## Compatibility

The App follows the DigitalHouses Application Standard and publishes one MQTT Discovery device. GitHub is the source of truth.
