# DigitalHouses Telemetry Implementation Guide

Status: implementation guide. Normative privacy and wire requirements are defined by:

- [DigitalHouses Product Telemetry Policy](PRODUCT_TELEMETRY_POLICY.md)
- [DigitalHouses Telemetry Protocol v1](TELEMETRY_PROTOCOL_V1.md)
- [DigitalHouses Release Policy](RELEASE_POLICY.md)

Use this document as the starting point in every product-specific implementation discussion.

## 1. Current production architecture

```text
DigitalHouses product
    -> HTTPS POST /v1/heartbeat
    -> Cloudflare
       -> derives country
    -> Cloudflare Tunnel
    -> DigitalHouses Stats
       -> FastAPI ingestion API
       -> PostgreSQL
```

Public endpoint:

```text
https://telemetry.digitalhouses.vip
```

The public telemetry process accepts ingestion/deletion only. Statistics are not part of the public API.

Current server behavior:

- heartbeat history is append-only;
- server receive time is authoritative;
- country is derived server-side;
- source IP is not stored in the telemetry database;
- there is currently no automatic retention cleanup;
- authenticated deletion removes the installation and all of its heartbeat history.

## 2. Current protocol v1 product allowlist

The production server allowlist is derived from the canonical product registry:

`digitalhouses-stats/digitalhouses_stats/product_registry.json`

All registry entries with `telemetry_allowed: true` are accepted before their clients necessarily start reporting. This intentionally lets development products exist in the Stats catalog with zero observed installations and prevents product/server rollout ordering from causing an avoidable `422 unsupported product`.

Registry admission does not enable telemetry in a product. A client must still be implemented, opt-in, default OFF, and release-gated before it contributes production observations.

### Internet App naming

The canonical repository, release and telemetry identifier for DigitalHouses Internet App is:

```text
digitalhouses_internet_app
```

The legacy `digitalhouses_speedtest_app` identifier remains a separate product identity and is not reused for the new Internet App. Release Policy, telemetry protocol/server allowlists, product payload and documentation use `digitalhouses_internet_app` consistently.

## 3. Required client payload

Heartbeat:

```http
POST /v1/heartbeat
Authorization: Bearer <installation_token>
Content-Type: application/json
```

```json
{
  "schema": 1,
  "telemetry_policy_version": 1,
  "installation_id": "550e8400-e29b-41d4-a716-446655440000",
  "product": "digitalhouses_pve_agent",
  "version": "0.5.10"
}
```

No additional fields are allowed in protocol v1.

The client must not send:

- country;
- source/public IP;
- hostname;
- customer/site/project name;
- Home Assistant UUID;
- MAC address;
- LAN IP;
- coordinates/city;
- entity IDs;
- device inventory;
- MQTT configuration;
- credentials;
- serial numbers;
- arbitrary diagnostics.

## 4. Installation identity

Every fresh installation creates:

```text
installation_id    UUIDv4
installation_token cryptographically secure random 256-bit secret
```

Requirements:

- created once;
- persisted across restart and upgrade;
- restored with supported backup/restore;
- not regenerated because the product version changes;
- token must never be logged;
- token file/state must be owner-only where the platform supports permissions.

Recommended persistence:

Linux Agent:

```text
/var/lib/digitalhouses/<product>/telemetry.json
```

Home Assistant App:

```text
/data/telemetry.json
```

An equivalent persistent representation is acceptable if it has the same lifecycle guarantees.

Suggested state shape:

```json
{
  "schema_version": 1,
  "installation_id": "...",
  "installation_token": "...",
  "last_attempt_epoch": 0,
  "last_success_epoch": 0,
  "last_reported_version": "..."
}
```

Scheduling fields may differ internally, but restart storms must be prevented.

## 5. Consent/configuration contract

Telemetry is opt-in and disabled by default.

Linux Agent example:

```ini
[telemetry]
enabled = false
```

Home Assistant App example:

```yaml
telemetry_enabled: false
```

The exact product configuration surface may differ, but the semantics must not:

- default OFF;
- disabled means no telemetry requests;
- telemetry failure never affects product health;
- disabling does not automatically delete historical server data;
- deletion is a separate authenticated action.

The user-facing option must link to the shared telemetry policy.

## 6. Scheduling contract

Normal successful cadence:

```text
24 hours ± 30 minutes
```

Allowed additional immediate best-effort heartbeat:

- first time telemetry is enabled;
- after successful upgrade to a new released version.

Recommended failure backoff:

```text
>= 1 hour
```

Recommended HTTP timeout:

```text
5 seconds
```

Telemetry must run outside the product's critical monitoring/control path.

It must not be coupled to:

- normal polling loops;
- MQTT publish loops;
- Home Assistant state updates;
- health checks;
- device-control cycles.

## 7. Release-build rule

Production telemetry must represent released product versions, not arbitrary development checkouts.

For Linux Agents, the implementation should verify that installed build provenance resolves to the canonical release tag:

```text
<release_identifier>-v<version>
```

and a valid exact commit SHA.

For Home Assistant Apps, telemetry must come from the immutable released App/image provenance defined by the Release Policy.

Development/main/temporary builds should not contribute production adoption statistics.

## 8. Heartbeat success/failure behavior

Success:

```text
HTTP 2xx
```

Preferred server response is `204 No Content`.

On success, persist enough local state to avoid another heartbeat until the next scheduled window unless the version changes.

On failure:

- do not fail product startup;
- do not mark the product unhealthy;
- do not retry aggressively;
- emit at most a concise diagnostic log;
- continue normal product operation.

## 9. Authenticated deletion

Request:

```http
DELETE /v1/installation
Authorization: Bearer <installation_token>
Content-Type: application/json
```

```json
{
  "schema": 1,
  "installation_id": "550e8400-e29b-41d4-a716-446655440000",
  "product": "digitalhouses_pve_agent"
}
```

The client may treat both successful 2xx responses and `404 Not Found` as operationally complete deletion.

The server verifies the per-installation token. Installation ID alone is never sufficient authorization.

Server-side deletion removes:

- installation credential record;
- all retained heartbeat history for that installation.

## 10. Server-side storage semantics

The current production model intentionally keeps identity/credential state separate from observation history.

`installations`:

```text
product
installation_id
installation_token_hash
created_at
```

Primary key:

```text
(product, installation_id)
```

`heartbeats`:

```text
id
received_at
product
installation_id
version
country
telemetry_policy_version
```

Every accepted heartbeat appends one observation row.

The server does not trust a client timestamp. `received_at` is generated server-side.

The database does not contain a source-IP column.

## 11. Country semantics

The client never sends country.

Production flow:

```text
request source
    -> Cloudflare derives CF-IPCountry
    -> telemetry service validates/normalizes
    -> PostgreSQL stores two-letter country code
```

Missing, malformed, or non-country values are normalized to:

```text
XX
```

Do not add application-level IP geolocation while the trusted edge already provides country.

## 12. Statistics semantics

Because telemetry is voluntary, counts are not total users or total installed base.

Use:

```text
observed installations
active 24h
active 7d
active 30d
```

Current calculations:

- observed installation = retained row in `installations`;
- active 24h/7d/30d = installation with at least one heartbeat in that window;
- version distribution = latest heartbeat version for each retained installation;
- country distribution = latest heartbeat country for each retained installation;
- history = unique active installations and heartbeat count grouped by server UTC day.

The local dashboard is an operator tool and is currently available only on the DigitalHouses LAN.

## 13. Retention

Current production decision:

```text
No automatic telemetry retention cleanup is enabled.
```

Heartbeat history is retained to support long-term dynamics until:

- the installation performs authenticated deletion; or
- a future repository-level policy explicitly introduces retention.

Do not implement a product-specific retention assumption.

Any future retention change must update, together:

- Product Telemetry Policy;
- Telemetry Protocol;
- stats server;
- tests;
- operator/legal wording.

## 14. Minimum implementation tests

Every product telemetry integration must cover at least:

```text
default OFF -> no HTTP requests
enable -> immediate eligible heartbeat
fresh install -> UUID/token created
restart -> same identity
upgrade -> same identity, new version
daily cadence -> no restart storm
failure -> product remains operational
wrong/malformed state -> safely repaired or regenerated
payload -> exact protocol v1 fields only
country -> absent from client payload
release provenance -> development build does not pollute production telemetry
successful heartbeat -> scheduling state persisted
delete -> correct product/ID/token request
token -> never logged
```

For Home Assistant Apps also test:

```text
backup/restore -> same installation identity
/data persistence -> survives App upgrade/recreation
```

## 15. Product integration checklist

Before implementation:

- [ ] confirm canonical product/release identifier;
- [ ] confirm server allowlist contains that identifier;
- [ ] confirm product version source;
- [ ] define persistent telemetry state location;
- [ ] define user-facing opt-in setting, default OFF;
- [ ] link user-facing setting to shared telemetry policy.

Implementation:

- [ ] UUIDv4 + 256-bit token creation;
- [ ] strict protocol v1 payload;
- [ ] 24h ±30m schedule;
- [ ] failure backoff;
- [ ] release-build gating;
- [ ] independent background runner/task;
- [ ] authenticated delete;
- [ ] secret-safe logging.

Verification:

- [ ] unit tests green;
- [ ] repository CI green;
- [ ] install/update test on real target;
- [ ] first real heartbeat visible in DigitalHouses Stats;
- [ ] version correct;
- [ ] country derived by server;
- [ ] no client country field;
- [ ] no IP persisted;
- [ ] disabling stops future heartbeats;
- [ ] deletion removes installation/history when tested.

## 16. Current rollout status

As of the current repository implementation:

| Product | Identifier | Production telemetry client |
| --- | --- | --- |
| DigitalHouses PVE Agent | `digitalhouses_pve_agent` | implemented and verified |
| DigitalHouses Plex Agent | `digitalhouses_plex_agent` | pending product implementation |
| DigitalHouses Recorder App | `digitalhouses_recorder_app` | pending product implementation |
| DigitalHouses Speedtest App | `digitalhouses_speedtest_app` | pending product implementation |
| DigitalHouses Backblaze App | `digitalhouses_backblaze_app` | client exists; admitted to registry/server allowlist; release-gating review required before production enablement |
| DigitalHouses Internet App | `digitalhouses_internet_app` | implemented in product and admitted to protocol/server allowlist |
| DigitalHouses Climate App | `digitalhouses_climate_app` | client implemented; admitted to protocol/server allowlist; real-install verification pending |

This table is operational status, not a replacement for the normative protocol or Release Policy.


## 17. Product-chat handoff template

Use this when starting telemetry work in a product-specific development discussion:

```text
Implement/review telemetry for <PRODUCT> according to the repository shared contract:

docs/standards/TELEMETRY_IMPLEMENTATION_GUIDE.md
docs/standards/TELEMETRY_PROTOCOL_V1.md
docs/standards/PRODUCT_TELEMETRY_POLICY.md
docs/standards/RELEASE_POLICY.md

First audit the current product implementation and report any contract mismatch.

Required constraints:
- telemetry remains opt-in and default OFF;
- protocol v1 payload is exact; do not add product-specific fields;
- country is never sent by the client;
- persistent UUIDv4 + 256-bit token survive restart/upgrade/restore;
- 24h ±30m heartbeat with persisted scheduling and non-aggressive failure backoff;
- telemetry failure cannot affect core product operation;
- production adoption must not be polluted by development builds;
- authenticated deletion uses the shared endpoint;
- tests cover identity, payload, timing, failure isolation and deletion.

Before enabling real telemetry, confirm the canonical product/release identifier is present in the shared stats-server allowlist.
Do not change shared telemetry semantics inside the product without updating the repository-level contract first.
```
