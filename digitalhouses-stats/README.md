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

## Local event journal (0.4.5)

The dashboard's **LOG** opens DH Journal 1.1.2 (RU/EN, search, level filter,
export and confirmed journal-only clear). It starts collecting on deployment;
historical heartbeats are not replayed. A routine unchanged heartbeat produces
no journal row. New registrations, upgrades/downgrades, country changes,
reporting resumed after at least seven days, and rate-limited validation
rejections are shown. A rejection records only safe field names, not payload
values. The derived journal contains product, version, country and event time,
not installation IDs, tokens, IPs or raw requests. Clearing the journal does
not alter PostgreSQL. Existing authenticated deletion semantics are unchanged.

SQLite is stored at /var/lib/digitalhouses-stats/journal.sqlite3 (3000 records).
The ingestion process owns the journal; the dashboard uses a fixed loopback
bridge authenticated by a rotating service-account-only key file. No journal
access is available through the public telemetry protocol. The LAN dashboard
is the trusted administrative surface; do not expose it publicly.
JOURNAL_PATH may be set in the service environment. Journal failures do not stop telemetry ingestion.


### Toast notifications (0.4.6)

The dashboard mounts the shared DH Journal Toast component. New registrations
and first observations of a country in retained PostgreSQL history are marked
for notification. When both happen together, show one combined toast and retain
both journal events. Ordinary heartbeats, version changes and rejected requests
do not display toasts. Unknown country codes XX and ZZ do not create new-country
notifications. The first toast is at the bottom right; later toasts appear above.
Settings are browser-local (enabled by default, 60 minutes, adjustable 1–1440).
Reload establishes a new cursor without replay. Dismissal affects only the UI.

The exact external library tag, commit and SHA-256 file manifest are recorded in
dh-journal.lock.json. The vendored package and dashboard assets are verified by
scripts/vendor_dh_journal.py --check. To regenerate from an already checked-out
pinned release, pass --stats-source PATH. No runtime download or extra store.

### Live dashboard refresh (0.4.7)

A new notification event batch invokes the existing dashboard data refresh via
DH Journal onEvents, even when toast presentation is disabled. Requests are
serialized and concurrent refresh requests coalesce into one follow-up.
Existing toast nodes, dismissal state, expiry timers, settings and expanded
country rows are independent of dashboard rendering. No new poll or service.

### LXC timezone (0.4.9)

DH Stats is an independent central statistics server. As an explicit exception
to the HA timezone authority rule, presentation uses the LXC system IANA
timezone from /etc/localtime. Ansible-CORE sets it to Asia/Almaty at deployment
and update. No HA API, HA package, MQTT timezone topic, token, cache or separate
timezone setting is required. LOG, export, toast and dashboard use this zone;
invalid system timezone falls back to UTC. Database sessions, historical
timestamps and UTC aggregate boundaries remain UTC.

### Browser favicon (0.4.10)

The LAN dashboard serves a deep-blue analytics favicon at /favicon.ico (16 and 32 px). The main page declares it explicitly; the shared LOG page uses the browser's standard root favicon lookup. No shared library changes.
