# Public Stats API

The public statistics API exposes aggregate telemetry only. It never returns
installation IDs or installation tokens.

Base URL:

```text
https://telemetry.digitalhouses.vip
```

## Summary

```text
GET /v1/stats/summary
```

Returns:

- observed installations currently retained in the installation table;
- active installations observed in the last 24 hours, 7 days and 30 days;
- total accepted heartbeat rows.

Example:

```json
{
  "observed_installations": 12,
  "active_24h": 10,
  "active_7d": 11,
  "active_30d": 12,
  "heartbeats": 318
}
```

## Products

```text
GET /v1/stats/products
```

Returns observed and active counts grouped by product.

## Versions

```text
GET /v1/stats/versions
GET /v1/stats/versions?product=digitalhouses_pve_agent
```

Each installation is counted only in the version from its latest heartbeat.
The response includes observed, active 7-day and active 30-day counts.

## Countries

```text
GET /v1/stats/countries
GET /v1/stats/countries?product=digitalhouses_pve_agent
```

Each installation is counted only in the country from its latest heartbeat.
The response includes observed, active 7-day and active 30-day counts.

`XX` means the country was unavailable or could not be normalized.

## History

```text
GET /v1/stats/history
GET /v1/stats/history?days=30
GET /v1/stats/history?days=30&product=digitalhouses_pve_agent
```

`days` defaults to 30 and accepts values from 1 through 3650.

Each UTC calendar day contains:

- unique installations that sent at least one heartbeat that day;
- total heartbeat rows received that day.

Missing days are returned with zero counts, which makes the endpoint suitable
for direct chart rendering.

## Counting semantics

An installation is the protocol identity `(product, installation_id)`.

A deleted installation no longer contributes to statistics because authenticated
deletion removes both its installation row and its heartbeat history.

The API performs queries directly against the normalized PostgreSQL tables.
There are no aggregate or rollup tables in this version.
