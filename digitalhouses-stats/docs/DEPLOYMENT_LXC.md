# Debian 12 LXC deployment

Target architecture:

```text
Internet agents
  -> Cloudflare
  -> Cloudflare Tunnel
  -> 127.0.0.1:8080
  -> telemetry ingestion API
  -> PostgreSQL

LAN browser
  -> 192.168.11.254:80
  -> nginx
  -> 127.0.0.1:8081
  -> local statistics API
  -> PostgreSQL
```

Statistics are intentionally absent from the public telemetry process.

The application must not be published directly on a WAN interface.

## Recommended LXC

Initial sizing:

- Debian 12
- 1 vCPU
- 1 GiB RAM
- 16 GiB disk
- normal LAN connectivity for package installation and outbound Cloudflare Tunnel

PostgreSQL may initially run in the same LXC. It can be moved later without changing
the application protocol.

## PostgreSQL

Create one database and one non-superuser role:

```text
database: digitalhouses_stats
role:     digitalhouses_stats
```

The password belongs only in:

```text
/etc/digitalhouses-stats/digitalhouses-stats.env
```

Example:

```text
DATABASE_URL=postgresql+psycopg://digitalhouses_stats:CHANGE_ME@127.0.0.1/digitalhouses_stats?client_encoding=utf8
LOG_LEVEL=INFO
```

Set the environment file mode to `0600`.

## Application

Install the checked-out `digitalhouses-stats` directory under:

```text
/opt/digitalhouses/digitalhouses-stats
```

Create a dedicated system account named `digitalhouses-stats`, create a Python
virtual environment, install the package, then apply the schema:

```bash
cd /opt/digitalhouses/digitalhouses-stats
python3 -m venv .venv
.venv/bin/pip install .
.venv/bin/alembic upgrade head
```

Install `deploy/digitalhouses-stats.service` as:

```text
/etc/systemd/system/digitalhouses-stats.service
```

Then enable and start it.

## Cloudflare Tunnel

Run `cloudflared` in the same LXC and publish:

```text
telemetry.digitalhouses.vip -> http://127.0.0.1:8080
```

Because the API listens only on loopback, arbitrary Internet clients cannot bypass
Cloudflare and inject a fake `CF-IPCountry` header directly into the application.

The application stores only the normalized country code from `CF-IPCountry`.
It does not define a source-IP database column.

Cloudflare values `T1`, missing values, and malformed values are stored as `XX`.

## Public boundary controls

Configure the Cloudflare endpoint to:

- allow HTTPS only;
- rate-limit `/v1/heartbeat` and `/v1/installation`;
- apply a small request-body limit at the edge;
- pass `CF-IPCountry`;
- avoid application or proxy logging that persists visitor source IP addresses.

Uvicorn is started with `--no-access-log`.

## Verification

Local health check:

```bash
curl -fsS http://127.0.0.1:8080/healthz
```

Expected:

```json
{"status":"ok"}
```

After the Cloudflare hostname is active, test the public health endpoint separately.

Do not enable production telemetry clients until the public privacy/operator wording
has completed the review required by the repository telemetry policy.


## Local dashboard

Install the dashboard after the application has been deployed:

```bash
cd /opt/digitalhouses/digitalhouses-stats
bash deploy/install-local-dashboard.sh
```

The dashboard is then available only from the LAN at:

```text
http://192.168.11.254/
```

The nginx virtual host binds specifically to `192.168.11.254:80`; it does not
listen on wildcard interfaces.
