# DigitalHouses Product Telemetry Policy

Status: normative architecture policy. Public distribution remains subject to final legal review.

Current telemetry policy version:

```text
telemetry_policy_version = 2
```

This policy applies to supported DigitalHouses products.

For products implemented in `DigitalHouses/home-assistant-apps`, the canonical product catalog is:

`digitalhouses-stats/digitalhouses_stats/product_registry.json`

A registry entry with `telemetry_allowed: true` is admitted to the production telemetry server allowlist. Active supported products admitted to telemetry must implement this policy. A product explicitly marked `lifecycle: deprecated` may retain its historical behavior and is not required to retrofit telemetry solely for standards conformance.

## 1. Purpose

DigitalHouses telemetry exists to measure real product adoption and support release operations.

The permitted product questions are:

- how many reporting installations have been observed;
- how many are active in the last 24 hours, 7 days, and 30 days;
- which products are active;
- which released versions are active;
- from which countries active installations report.

Telemetry is not a remote-management channel and must not become one.

## 2. Required product telemetry

Telemetry is part of normal operation for supported official DigitalHouses product releases.

A supported product must:

- create and persist its telemetry installation identity;
- attempt telemetry without requiring a separate consent toggle;
- send the minimum protocol heartbeat on the shared cadence;
- continue normal product operation when telemetry cannot reach the server.

The final supported configuration must not expose an option whose purpose is to disable telemetry. In particular, new production releases must not introduce or retain `telemetry_enabled` as an opt-out control after that product completes its policy-v2 migration.

Users must be told clearly, before installation or update, that supported DigitalHouses products report the minimal telemetry defined by this policy. A user who does not accept that product behavior should not install or continue using the supported official product.

Network blocking, DNS failure, firewall rules, endpoint failure, or other transport failures may prevent delivery in practice. Such failures must never disable or degrade the core product. Mandatory telemetry means the official client always attempts reporting; it does not mean the product may make telemetry availability a runtime dependency.

Legacy releases that implement policy version 1 remain valid historical releases. The server may accept policy versions 1 and 2 during migration, but new releases completing the mandatory-telemetry migration must use policy version 2.

## 3. Data minimization

Protocol v1 with telemetry policy version 2 may transmit only:

```text
schema
telemetry_policy_version
installation_id
product
version
```

The server may derive a two-letter ISO country code from request network metadata.

The client must not transmit:

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
- product configuration;
- monitoring results;
- diagnostics unrelated to telemetry.

Any expansion of collected fields requires a documented policy review before implementation. A change in telemetry participation does not authorize broader collection.

## 4. Pseudonymous installation identity

Each product installation has its own random identity:

```text
installation_id = UUIDv4
installation_token = cryptographically secure random 256-bit secret
```

The installation ID is a pseudonymous installation identifier. It must not be described as an anonymous user identifier.

The token authenticates mutation of that installation's telemetry record. It must never be used as an analytics dimension.

The identity is created once and must survive:

- restart;
- upgrade;
- container recreation;
- supported backup and restore.

Restoring an existing installation must preserve the existing identity.

A fresh installation must receive a fresh identity.

For Home Assistant Apps, identity state belongs in persistent `/data`.

For Linux Agents, identity state belongs under:

```text
/var/lib/digitalhouses/<product>/
```

## 5. Network metadata and country

Country is determined server-side from request source network metadata.

Only the ISO country code is retained in the telemetry data model:

```text
KZ
DE
US
...
```

City and coordinates are not collected.

The telemetry application database must not contain source IP addresses.

Infrastructure must be configured so that a statement such as "source IP addresses are not retained by the telemetry system" remains true across the controlled request path, including reverse proxy, CDN, load balancer, application access logs, and analytics services.

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

- on a fresh installation;
- after a successful product upgrade to a different released version;
- after a successful authenticated telemetry deletion when a fresh local installation identity has been created.

Clients must persist scheduling state sufficiently to avoid heartbeat storms after repeated restarts.

Telemetry must not be sent on every application loop or monitoring cycle.

## 7. Failure isolation

Telemetry is non-critical to core product operation.

DNS failure, timeout, TLS failure, HTTP errors, rate limiting, or telemetry-server unavailability must not:

- fail startup;
- stop the main runtime;
- delay critical product work;
- degrade monitoring/control behavior;
- be promoted to a product-health error.

At most, record a concise diagnostic message such as:

```text
Telemetry heartbeat failed; will retry later
```

Do not use aggressive retry loops.

Current retry guidance is at least one hour before retry eligibility.

## 8. Meaning of telemetry counts

Even with required telemetry, the server cannot prove the complete installed base because installations can be offline, blocked by network policy, modified, abandoned, or otherwise unable to report.

Do not label telemetry counts as "users" or as a guaranteed total installed base.

Use terminology such as:

```text
observed installations
reporting installations
active installations
```

Required activity windows:

```text
active 24h
active 7d
active 30d
```

Version and country distributions count each retained installation once, using the latest accepted heartbeat for that installation. Operator views may additionally scope those distributions to a defined active window, normally 7 days.

## 9. Retention

Current production policy does not enable automatic time-based telemetry retention cleanup.

Accepted heartbeat observations are retained to support long-term product/version/country dynamics until:

- the installation performs authenticated deletion; or
- a future repository-level policy revision introduces an explicit retention rule.

Therefore "observed installations" means retained telemetry installation identities, not users and not a guaranteed complete installed base.

No product may implement its own assumption that the server expires telemetry after a fixed number of days.

A future time-based retention policy is a material data-lifecycle change. It must update together:

- this policy;
- the shared telemetry protocol;
- the stats server implementation;
- tests;
- operator/user-facing wording.

## 10. Deletion

The telemetry API must provide an authenticated mechanism for an installation to delete its retained telemetry record.

`installation_id` alone is not authentication.

Deletion must require the installation token or an equivalent per-installation credential defined by the telemetry protocol.

Authenticated deletion removes:

- the installation credential record;
- all retained heartbeat history associated with that installation.

Under policy version 2, deletion does not disable future required telemetry while the product continues to be used.

After a successful deletion, the product must rotate its local `installation_id` and `installation_token` so any later telemetry starts under a fresh pseudonymous identity that is not linked by the telemetry data model to the deleted identity.

If the product remains installed and running, reporting resumes according to the normal cadence using that fresh identity. To stop future official-client reporting, the product must no longer be used.

User-facing controls must describe this accurately. Do not label deletion as a telemetry opt-out.

## 11. Security boundaries

Telemetry uses HTTPS only.

The server must:

- allow only registered DigitalHouses product identifiers;
- validate protocol schema;
- validate supported telemetry policy versions;
- validate UUID and Semantic Version formats;
- validate content type;
- enforce a small request-size limit;
- rate-limit public endpoints;
- store only a one-way hash of the installation token;
- reject malformed requests;
- expose no remote command mechanism through telemetry.

A shared secret embedded in open-source clients must not be treated as meaningful authentication.

Per-installation credentials protect mutation of an installation record. They do not prove that a request came from an unmodified official binary, so public-endpoint abuse protections remain necessary.

## 12. Transparency

All supported products must use materially equivalent user-facing disclosure.

Required meaning:

```text
DigitalHouses product telemetry

This product sends minimal pseudonymous operational telemetry to DigitalHouses:
product identifier, product version, a random installation identifier,
and country determined by the server from network metadata.

Telemetry reporting is part of supported product operation and has no
in-product opt-out. Core product operation does not depend on telemetry
server availability.

Source IP addresses are not retained by the DigitalHouses telemetry system.
```

The published policy must state:

- fields sent;
- purpose;
- frequency;
- current history-retention behavior;
- country derivation;
- IP handling;
- deletion behavior;
- that continued product use resumes reporting after deletion under a fresh identity;
- the data operator/controller identity and contact channel.

The public legal wording must be reviewed for applicable jurisdictions before mandatory telemetry is shipped broadly.

Do not ship a placeholder operator/controller identity in the public policy.

## 13. Protocol ownership and policy versioning

Wire behavior is defined by [DigitalHouses Telemetry Protocol v1](TELEMETRY_PROTOCOL_V1.md).

This policy defines why and under what privacy/security constraints telemetry exists. Product implementations must not invent product-specific telemetry semantics that contradict the shared protocol.

Policy version 2 changes telemetry participation from explicit opt-in to required reporting for supported products. It does not add telemetry payload fields and therefore does not require a new wire-schema version.

During migration:

```text
wire schema 1 + telemetry policy 1 = legacy opt-in client
wire schema 1 + telemetry policy 2 = supported mandatory-telemetry client
```

The telemetry service must accept both policy versions while policy-v1 releases remain in the supported migration population. New product releases that complete this migration must send policy version 2.
