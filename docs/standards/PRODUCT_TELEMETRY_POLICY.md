# DigitalHouses Product Telemetry Policy

Status: normative architecture policy. Public activation remains subject to final legal review.

This policy applies to products in `DigitalHouses/home-assistant-apps`.

Current mandatory scope:

- `digitalhouses_pve_agent`
- `digitalhouses_plex_agent`
- `digitalhouses_recorder_app`
- `digitalhouses_speedtest_app`
- `digitalhouses_backblaze_app`
- `digitalhouses_internet_app`

Future DigitalHouses products in this repository must follow the same telemetry contract unless an explicit repository-level exemption is documented.

Mandatory scope describes the repository target. It does not mean every listed product is already enabled in the production telemetry server. Production enablement additionally requires the shared protocol/server allowlist and the product implementation to be updated together. Current operational status is maintained in [DigitalHouses Telemetry Implementation Guide](TELEMETRY_IMPLEMENTATION_GUIDE.md).

## 1. Purpose

DigitalHouses telemetry exists only to measure product adoption and support release operations.

The permitted product questions are:

- how many telemetry-enabled installations have been observed;
- how many are active in the last 24 hours, 7 days, and 30 days;
- which products are active;
- which released versions are active;
- from which countries active installations report.

Telemetry is not a remote-management channel and must not become one.

## 2. Consent

Telemetry is opt-in.

The default for every product is:

```text
telemetry_enabled = false
```

No telemetry request may be sent before the user explicitly enables telemetry.

Disabling telemetry stops future heartbeats. Product operation must remain unchanged whether telemetry is enabled, disabled, blocked, or unavailable.

The user-facing setting must link to the published DigitalHouses Product Telemetry Policy.

## 3. Data minimization

Protocol v1 may transmit only:

```text
schema
telemetry_policy_version
installation_id
product
version
```

The server may derive a two-letter ISO country code from request network metadata.

Protocol v1 must not transmit:

- hostname;
- customer, household, site, or project name;
- Home Assistant installation UUID;
- MAC address;
- LAN IP address;
- WAN IP address as payload data;
- coordinates or city;
- entity IDs;
- device inventories;
- MQTT broker information;
- serial numbers;
- email;
- username;
- configuration values unrelated to telemetry.

Any expansion of collected fields requires a new documented policy/protocol revision before implementation.

## 4. Pseudonymous installation identity

Each product installation has its own random identity:

```text
installation_id = UUIDv4
installation_token = cryptographically secure random 256-bit secret
```

The installation ID is a pseudonymous installation identifier. It must not be described as an anonymous user identifier.

The token is an authentication credential for that installation. It must never be used as an analytics dimension.

The identity is created once and must survive:

- restart;
- upgrade;
- container recreation;
- Home Assistant backup and restore when applicable.

Restoring an existing installation must preserve the existing identity.

A fresh installation must receive a fresh identity.

For Home Assistant Apps, identity state belongs in persistent `/data`.

For Linux Agents, identity state belongs under:

```text
/var/lib/digitalhouses/<product>/
```

## 5. Network metadata and country

Country is determined server-side from the request source network metadata.

Only the ISO country code is retained in the telemetry data model:

```text
KZ
DE
US
...
```

City and coordinates are not collected.

The telemetry application database must not contain source IP addresses.

Infrastructure must also be configured so that claims such as "IP address is not stored" remain true across the complete request path, including reverse proxy, CDN, load balancer, application access logs, and analytics services.

Where an edge provider can provide a trustworthy country code, the preferred architecture is to pass only that country code to the telemetry application instead of performing application-level IP geolocation.

## 6. Frequency

Normal cadence:

```text
1 successful heartbeat target per 24 hours
```

Clients must add jitter so installations do not synchronize.

Recommended window:

```text
24h ± 30 min
```

An immediate best-effort heartbeat is allowed:

- when telemetry is enabled for the first time;
- after a successful product upgrade to a different released version.

Clients must persist scheduling state sufficiently to avoid a heartbeat storm after repeated restarts.

Telemetry must not be sent on every application loop or monitoring cycle.

## 7. Failure isolation

Telemetry is best-effort and non-critical.

DNS failure, timeout, TLS failure, HTTP errors, rate limiting, or telemetry-server unavailability must not:

- fail startup;
- stop the main runtime;
- delay critical product work;
- degrade monitoring behavior;
- be promoted to a product-health error.

At most, record a diagnostic log message such as:

```text
Telemetry heartbeat failed; will retry later
```

Do not use aggressive retry loops.

## 8. Meaning of telemetry counts

Telemetry cannot measure all installations because telemetry is voluntary.

Do not label telemetry counts as "users" or as the total installed base.

Use terminology such as:

```text
observed installations
telemetry-enabled installations
active telemetry installations
```

Required activity windows:

```text
active 24h
active 7d
active 30d
```

Version and country distributions must count each retained installation once, using the latest accepted heartbeat for that installation. Operator views may additionally scope those distributions to a defined active window, normally 7 days.

## 9. Retention

Current production policy does not enable automatic time-based telemetry retention cleanup.

Accepted heartbeat observations are retained to support long-term product/version/country dynamics until:

- the installation performs authenticated deletion; or
- a future repository-level policy revision introduces an explicit retention rule.

Therefore "observed installations" means retained telemetry-enabled installation identities, not the complete installed base and not a count of users.

No product may implement its own assumption that the server expires telemetry after a fixed number of days.

A future time-based retention policy is a material data-lifecycle change. It must update together:

- this policy;
- the shared telemetry protocol;
- the stats server implementation;
- tests;
- operator/user-facing wording.

## 10. Deletion

The telemetry API must provide an authenticated mechanism for an installation to delete its own telemetry record.

`installation_id` alone is not authentication.

Deletion must require the installation token or an equivalent per-installation credential defined by the telemetry protocol.

Authenticated deletion removes the installation credential record and all retained heartbeat history associated with that installation.

Disabling telemetry and deleting the server-side record are separate actions:

- disable: stop future heartbeats;
- delete: remove the retained installation identity and its heartbeat history.

## 11. Security boundaries

Telemetry uses HTTPS only.

The server must:

- allow only registered DigitalHouses product identifiers;
- validate protocol schema;
- validate UUID and semantic version formats;
- validate content type;
- enforce a small request-size limit;
- rate-limit public endpoints;
- store only a one-way hash of the installation token;
- reject malformed requests;
- expose no remote command mechanism through telemetry.

A shared secret embedded in open-source clients must not be treated as meaningful authentication.

Per-installation credentials protect mutation of an installation record. They do not prove that a request came from an unmodified official binary, so public-endpoint abuse protections remain necessary.

## 12. Transparency

All products must use materially equivalent user-facing disclosure.

Required meaning:

```text
Usage telemetry

Send DigitalHouses minimal pseudonymous usage statistics:
product name, product version, a random installation identifier,
and country determined by the server from network metadata.

Telemetry is optional and disabled by default.
Source IP addresses are not retained by the telemetry system.
```

The published policy must state:

- fields sent;
- purpose;
- frequency;
- current history-retention behavior;
- country derivation;
- IP handling;
- how to disable telemetry;
- how to delete retained telemetry data;
- the data operator/controller identity and contact channel.

The public legal wording must be reviewed for applicable jurisdictions before telemetry is enabled in publicly distributed releases.

Do not ship a placeholder operator/controller identity in the public policy.

## 13. Protocol ownership

Wire behavior is defined by [DigitalHouses Telemetry Protocol v1](TELEMETRY_PROTOCOL_V1.md).

This policy defines why and under what privacy/security constraints telemetry exists. Product implementations must not invent product-specific telemetry semantics that contradict the shared protocol.
