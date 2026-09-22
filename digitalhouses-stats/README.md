# DigitalHouses Stats

Backend for DigitalHouses opt-in product telemetry and public statistics.

The wire contract is defined by:

- `docs/standards/TELEMETRY_PROTOCOL_V1.md`
- `docs/standards/PRODUCT_TELEMETRY_POLICY.md`

## MVP scope

- `POST /v1/heartbeat`
- `DELETE /v1/installation`
- `GET /healthz`
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

See `docs/DEPLOYMENT_LXC.md` for the intended Debian 12 LXC deployment.
