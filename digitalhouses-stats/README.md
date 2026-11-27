# DigitalHouses Stats

Backend for DigitalHouses product telemetry and LAN-only statistics.

The wire contract is defined by:

- `docs/standards/TELEMETRY_PROTOCOL_V1.md`
- `docs/standards/PRODUCT_TELEMETRY_POLICY.md`

The canonical product catalog is `digitalhouses_stats/product_registry.json`. The telemetry allowlist, dashboard product names, zero-count product rows, and repository release tooling derive from this registry. A registry entry may exist before the product telemetry client completes rollout. The ingestion service accepts legacy telemetry policy v1 and current mandatory telemetry policy v2 during migration.

## MVP scope

- `POST /v1/heartbeat`
- `DELETE /v1/installation`
- `GET /healthz`
- local dashboard API on `127.0.0.1:8081`
- LAN dashboard on `http://192.168.11.254/`
- PostgreSQL storage
- append-only heartbeat history
- server-side timestamps
- country derived from trusted Cloudflare `CF-IPCountry`
- no telemetry retention job
- no source-IP column

## Storage model

`installations` stores the installation identity and only a SHA-256 hash of the
256-bit random installation token.

`heartbeats` stores every accepted heartbeat as an immutable observation:

- server receive timestamp;
- product;
- installation ID;
- product version;
- country;
- telemetry policy version.

This preserves longitudinal data for later SQL reports without pre-aggregating it.

## Development

```bash
cd digitalhouses-stats
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
export DATABASE_URL='postgresql+psycopg://digitalhouses_stats:password@127.0.0.1/digitalhouses_stats'
alembic upgrade head
uvicorn digitalhouses_stats.main:app --host 127.0.0.1 --port 8080
```

See `docs/DEPLOYMENT_LXC.md` for the Debian 12 LXC deployment and `docs/LOCAL_DASHBOARD.md` for the LAN-only dashboard.

The LAN dashboard combines country and product counts in one table: full English country names, App/Agent counts below each country, and a grand total. The breakdown uses only aggregated, latest-country counts and is not exposed by the public telemetry API.

## New-country notifications (MQTT)

Stats can publish a one-time non-retained MQTT event when a **new country**
first appears in received heartbeat history. The notifier runs from a systemd
timer every minute, independently of ingestion.

- Topic: `DigitalHouses/Global/digitalhouses_stats/event/new_country`
- QoS 1, retain false; JSON fields: `schema`, `event_type`,
  `country`, `country_name`, `country_count`, `first_seen`.
- The `country_count` matches the current dashboard count (latest reported
  country per installation). `first_seen` is the earliest stored heartbeat
  timestamp in UTC; display time zone is handled in Home Assistant.
- On the first run, the state file is initialized from all historically
  observed countries. Existing countries do not produce notifications.
- Published countries are saved after broker PUBACK. Failed sends retry at
  the next run. A country change via VPN can count as a new country.
- No Telegram bot is required on Stats. CORE HA (`192.168.11.242`) subscribes
  to the MQTT event and sends directly to the configured group with
  `notify.send_message`, `entity_id: notify.dh_core_group`. The legacy global
  Telegram dispatcher and `write2admins` are not needed for Stats events.

See `deploy/digitalhouses-stats-country-notifier.service`,
`deploy/digitalhouses-stats-country-notifier.timer`, and
`integrations/ha_country_notification_package.yaml`.

### Product succession

Actions App supersedes Aqara Switch App. Both IDs remain in the catalog and telemetry allowlist; the historical Aqara ID is deprecated and is not release-managed. Installations and heartbeats remain keyed by the original product ID. Do not rewrite or combine historical records automatically.
