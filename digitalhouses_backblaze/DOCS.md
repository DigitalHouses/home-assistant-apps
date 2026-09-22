# DigitalHouses Backblaze App — Operations

## Architecture

```text
Backblaze B2 Native API v4
        |
        | HTTPS
        v
DigitalHouses Backblaze App
        |
        | MQTT Device Discovery
        v
Home Assistant
```

The App authorizes with `b2_authorize_account`, discovers accessible buckets with `b2_list_buckets`, then scans every bucket with paginated `b2_list_file_versions`.

## Storage semantics

`Storage used` is the sum of `contentLength` for every completed file version whose action is `upload`.

This intentionally includes historical file versions because those bytes remain stored in B2.

The v0.1.0 metric does not include unfinished large-file parts. That limitation must remain visible until explicit unfinished-part accounting is implemented.

## Update model

- immediate scan at App start;
- automatic scan every `refresh_interval_hours`;
- on-demand scan through `button.dh_backblaze_refresh`.

Backblaze scanning is intentionally low-frequency because a bucket may require many paginated list operations.

## Credentials

The recommended key is dedicated to this App and has only:

```text
listBuckets
listFiles
```

No read-file-content, write, delete, bucket-administration, or key-administration capability is required.

## MQTT

Base topic:

```text
DigitalHouses/Global/backblaze
```

Device discovery topic:

```text
homeassistant/device/digitalhouses_global_backblaze/config
```

All entities belong to one Home Assistant device.

## Persistent state

Only DigitalHouses telemetry identity/scheduling state is persisted under `/data/telemetry_state.json`.

Backblaze credentials are supplied by Home Assistant App options and are not copied to application-owned state files.

## Telemetry

`telemetry_enabled` defaults to `false`.

DigitalHouses telemetry is operationally independent of Backblaze collection. Telemetry failure must not affect App startup, B2 collection, MQTT publication, or manual refresh.
