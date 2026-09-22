# DigitalHouses Telemetry Protocol v1

Status: normative protocol contract.

This document defines one telemetry protocol for all DigitalHouses products in `DigitalHouses/home-assistant-apps`.

It must be implemented consistently by:

- `digitalhouses_pve_agent`
- `digitalhouses_plex_agent`
- `digitalhouses_recorder_app`
- `digitalhouses_speedtest_app`
- future products that participate in DigitalHouses telemetry.

Privacy and consent requirements are defined by [DigitalHouses Product Telemetry Policy](PRODUCT_TELEMETRY_POLICY.md).

## 1. Design goals

Protocol v1 is intentionally small.

It provides:

- opt-in installation heartbeat;
- current product/version observation;
- country aggregation;
- active-window reporting;
- authenticated deletion of one installation record.

It does not provide:

- remote configuration;
- remote commands;
- feature flags;
- software update control;
- arbitrary server-to-client messages.

## 2. Product identifiers

Allowed v1 product identifiers:

```text
digitalhouses_pve_agent
digitalhouses_plex_agent
digitalhouses_recorder_app
digitalhouses_speedtest_app
```

The server rejects unknown product identifiers.

Product identifiers are release/product identities. They do not require runtime service names, App slugs, MQTT identifiers, or repository directories to be renamed.

## 3. Installation credentials

Every installation creates:

```text
installation_id
installation_token
```

Requirements:

- `installation_id`: UUIDv4;
- `installation_token`: at least 256 bits from a cryptographically secure random generator;
- both created once per fresh installation;
- both persisted across restart and upgrade;
- both restored with the installation backup where applicable.

The token must not be logged or included in analytics output.

The server stores only a one-way cryptographic hash of the token.

## 4. Heartbeat request

Endpoint:

```http
POST /v1/heartbeat
```

Transport:

```text
HTTPS only
Content-Type: application/json
Authorization: Bearer <installation_token>
```

Payload:

```json
{
  "schema": 1,
  "telemetry_policy_version": 1,
  "installation_id": "550e8400-e29b-41d4-a716-446655440000",
  "product": "digitalhouses_recorder_app",
  "version": "0.1.9"
}
```

No additional product-specific data is permitted in protocol v1.

The preferred success response is:

```http
204 No Content
```

The client must not depend on a response body.

## 5. First heartbeat and authentication

For a previously unseen `(product, installation_id)`:

1. validate request structure and public-endpoint limits;
2. derive the permitted country code;
3. hash the supplied installation token;
4. create the installation record;
5. set `first_seen = now` and `last_seen = now`.

For an existing `(product, installation_id)`:

1. verify the supplied token against the stored token hash;
2. reject the request if verification fails;
3. update mutable telemetry fields;
4. keep `first_seen` unchanged.

A random UUID makes accidental installation-ID collision negligible. Rate limiting and abuse controls are still required because this is a public endpoint.

## 6. Heartbeat update semantics

On accepted heartbeat:

```text
version                  = current product version
country                  = current derived ISO country code
telemetry_policy_version = current client policy version
last_seen                = now
```

`first_seen` never changes after record creation.

The server must not create a new record merely because product version changes.

## 7. Delete request

Endpoint:

```http
DELETE /v1/installation
```

Transport:

```text
HTTPS only
Content-Type: application/json
Authorization: Bearer <installation_token>
```

Payload:

```json
{
  "schema": 1,
  "installation_id": "550e8400-e29b-41d4-a716-446655440000",
  "product": "digitalhouses_recorder_app"
}
```

The server verifies the token for that `(product, installation_id)` before deletion.

Preferred successful result:

```http
204 No Content
```

Deletion must be idempotent from the client's operational perspective.

`installation_id` alone must never authorize deletion.

## 8. Client timing

Normal target:

```text
1 heartbeat / 24h
```

Recommended jitter:

```text
24h ± 30 min
```

A client may additionally send one best-effort heartbeat:

- immediately after telemetry becomes enabled;
- after a successful upgrade that changes the product version.

The client must persist enough scheduling state to prevent repeated restart-triggered heartbeats.

After a failed attempt, use a reasonable backoff or wait until the next normal window. Do not retry aggressively.

## 9. Client failure behavior

Telemetry runs outside the critical product path.

Failures including:

```text
DNS failure
connection timeout
TLS failure
HTTP 4xx
HTTP 5xx
rate limit
server unavailable
```

must not alter normal product operation.

A diagnostic log entry is allowed. Repeated errors must not flood logs.

## 10. Server validation

The server must validate at least:

- HTTPS transport at the public boundary;
- `Content-Type: application/json`;
- small maximum request body size;
- exact supported schema version;
- exact supported product identifier;
- valid UUIDv4 installation ID;
- valid Semantic Version product version;
- supported telemetry policy version;
- required Authorization bearer token;
- token length/format;
- no unsupported payload expansion when strict schema validation is used.

Malformed requests are rejected without creating telemetry records.

## 11. Country derivation

Country is server-derived and stored as a two-letter ISO code.

The client does not send country.

The telemetry application must not persist source IP.

If a trusted edge/CDN already derives country, the preferred flow is:

```text
source request
    ↓
trusted edge derives country
    ↓
telemetry service receives trusted country code
    ↓
telemetry database stores ISO code only
```

Any edge header used for country must be accepted only from the trusted proxy path and must not be trusted directly from arbitrary internet clients.

## 12. Data model

Minimum installation record:

```text
installation_id
product
version
country
first_seen
last_seen
telemetry_policy_version
installation_token_hash
```

Unique key:

```text
(product, installation_id)
```

Source IP must not be a telemetry database column.

## 13. Required aggregate views

Required metrics:

```text
observed installations
active 24h
active 7d
active 30d
```

Required version report, normally scoped to active 7d:

```text
digitalhouses_pve_agent

0.5.8    143
0.5.7     18
0.5.6      4
```

Required country report, normally scoped to active 7d:

```text
KZ   126
DE    21
US    18
PL     7
```

Do not label these values as users or total installations.

## 14. Security and abuse resistance

At minimum:

- HTTPS only;
- endpoint rate limiting;
- strict request-size limit;
- product allowlist;
- strict schema validation;
- per-installation token verification;
- token hashes at rest;
- no token logging;
- no remote command response;
- no trust in a shared secret shipped with open-source clients.

Per-installation credentials protect an existing record from unauthorized mutation/deletion. They are not software attestation and do not prove that a request originated from an official unmodified build.

## 15. Versioning

`schema: 1` identifies this wire contract.

Backward-incompatible wire changes require a new protocol schema.

Adding a new telemetry data field also requires privacy-policy review before protocol adoption.

Product release versions remain governed by [DigitalHouses Release Policy](RELEASE_POLICY.md).
