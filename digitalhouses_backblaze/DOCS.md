# DigitalHouses Backblaze documentation

## Configuration

Required:

- application_key_id: Backblaze application key ID.
- application_key: Backblaze application key secret.

Optional:

- refresh_interval_hours: full account scan interval, default 6 hours.
- telemetry_enabled: DigitalHouses product telemetry opt-in, default false.
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

## Product telemetry

Telemetry is independent of Backblaze collection and disabled by default.

When enabled, a separate worker targets one successful heartbeat per 24 hours with deterministic jitter of up to 30 minutes. Failures use backoff and never affect B2 collection, MQTT, startup or manual refresh.

Persistent telemetry identity is stored in:

```text
/data/telemetry_state.json
```

The heartbeat payload is restricted to the common protocol-v1 fields. Backblaze credentials and storage/account/bucket data are never sent to the DigitalHouses telemetry service.

The Home Assistant `Delete telemetry data` button sends the authenticated protocol-v1 DELETE request using the persistent per-installation token.

## Security

The Backblaze secret is read from Home Assistant App options and is never published through MQTT, telemetry, or logs.

Use a dedicated read-only application key rather than the master key.
