# DigitalHouses Backblaze documentation

## Configuration

Required:

- application_key_id: Backblaze application key ID.
- application_key: Backblaze application key secret.

Optional:

- refresh_interval_hours: full account scan interval, default 6 hours.
- log_level: debug, info, warning, or error.

The key should have listBuckets and listFiles and no write/delete capabilities.

## Collection

Each refresh performs:

1. b2_authorize_account using B2 Native API v4.
2. b2_list_buckets for all buckets visible to the key.
3. paginated b2_list_file_versions for every bucket.
4. aggregation of stored bytes, current visible files, and completed content-bearing versions.
5. retained MQTT state publication and MQTT Discovery update.

A file hidden by a hide marker remains included in stored bytes while its retained historical upload version exists. It is not counted as a current visible file.

Started large files are ignored for current-file determination. Uploaded parts of unfinished large files are not included in version 0.1.0 storage totals.

## MQTT

Base topic: DigitalHouses/Global/backblaze

Discovery device ID: digitalhouses_backblaze

Home Assistant status is observed so retained discovery/state can be republished after Home Assistant starts.

## Security

The Backblaze secret is read from Home Assistant App options and is never published through MQTT or written to logs.

Use a dedicated read-only application key rather than the master key.
