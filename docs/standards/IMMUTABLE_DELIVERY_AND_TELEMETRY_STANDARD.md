# DigitalHouses Immutable Delivery, Compact Backup and Telemetry Standard

Status: normative implementation standard.

Repository:

```text
DigitalHouses/home-assistant-apps
```

This standard defines the target production architecture for release artifacts, Home Assistant App backups, and product telemetry.

It is mandatory for the participating product set:

```text
digitalhouses_pve_agent
digitalhouses_plex_agent
digitalhouses_recorder_app
digitalhouses_speedtest_app
digitalhouses_backblaze_app
digitalhouses_internet_app
```

The Home Assistant image/backup requirements apply only to Home Assistant Apps. The release identity and telemetry requirements apply to all participating products.

## 1. Architecture goal

DigitalHouses products must have one consistent production model:

```text
SOURCE / RELEASE
version
   ↕
canonical Git tag
   ↓
exact commit SHA
   ↓
immutable release artifact

HOME ASSISTANT APPS
immutable GHCR image
   ↓
DigitalHouses App repository
   ↓
Home Assistant Supervisor

BACKUP
configuration + installation-specific persistent state
without locally built application images

TELEMETRY
opt-in product heartbeat
   ↓
telemetry.digitalhouses.vip
   ↓
product / version / installation identity / country / activity
```

The architecture deliberately separates deployment from telemetry. A product must remain fully functional without telemetry.

## 2. Implementation order

Implementation is staged.

### Stage A — immutable Home Assistant App delivery

Implement first for:

```text
digitalhouses_recorder_app
digitalhouses_speedtest_app
```

Required outcome:

- production Apps are installed from the DigitalHouses App repository;
- application code is delivered through versioned GHCR images;
- local-image backup duplication is removed;
- old released images remain recoverable.

DigitalHouses Backblaze App and DigitalHouses Internet App were introduced after this rollout sequence was written. Each must satisfy the same immutable Home Assistant App delivery contract before its first production release; an experimental source-only implementation is not a completed production release.

### Stage B — shared telemetry service and protocol

Implement:

- one telemetry service;
- protocol v1;
- persistent installation credentials;
- append-only heartbeat history;
- server-side receive timestamps;
- country derivation;
- authenticated deletion;
- aggregate reports.

Current production policy intentionally has no automatic time-based retention cleanup.

### Stage C — product integration

Integrate the same telemetry client semantics into:

```text
digitalhouses_pve_agent
digitalhouses_plex_agent
digitalhouses_recorder_app
digitalhouses_speedtest_app
digitalhouses_backblaze_app
```

Do not combine the first immutable-delivery migration of a Home Assistant App with its first telemetry implementation in the same product release unless a documented exception is approved.

This separation keeps deployment risk and network-feature risk independently diagnosable.

---

# Part I — Immutable Home Assistant App delivery

## 3. Production release identity

For every Home Assistant App release, the following identities must describe the same source release:

```text
config.yaml version
GitHub Release version
canonical Git release tag
exact Git commit SHA
GHCR image version tag
GHCR image digest
```

Canonical release tag:

```text
<release_identifier>-v<version>
```

Examples:

```text
digitalhouses_recorder_app-v0.1.9
digitalhouses_speedtest_app-v1.2.2
```

Image repository naming is mechanical:

```text
ghcr.io/digitalhouses/<canonical_product_id>
```

The canonical ID is used unchanged, including underscores. No alternate dashed image/product identity is stored.

Example image identities:

```text
ghcr.io/digitalhouses/digitalhouses_recorder_app:0.1.9
ghcr.io/digitalhouses/digitalhouses_speedtest_app:1.2.2
```

The image digest is the exact artifact identity:

```text
sha256:<digest>
```

A human-readable version tag is required for operations. The digest is required for exact provenance and verification.

## 4. No mutable production deployment

Production deployment must never depend on:

```text
latest
main
a development branch
a mutable floating image tag
an arbitrary unpublished build
```

Once a versioned image is published, that version must not be overwritten with different image content.

New code requires a new product version.

Released images should remain available for disaster recovery of historical backups.

## 5. Home Assistant App image contract

A production Home Assistant App must reference the published image repository through its App package metadata.

The product version remains the version source of truth.

Conceptually:

```yaml
version: "0.1.9"
image: "ghcr.io/digitalhouses/digitalhouses-recorder-app"
```

The delivery implementation must follow the current Home Assistant Supervisor App image contract and must keep the package version and container image version aligned.

Where multiple architectures are supported, prefer one published multi-architecture image/manifest when supported by the delivery platform.

Do not introduce architecture-specific naming unless required by the platform.

## 6. Build provenance

The release pipeline must build the Home Assistant App image from the exact released source revision.

Required provenance chain:

```text
product version
    ↕
release tag
    ↓
exact main commit SHA
    ↓
GHCR image version tag
    ↓
GHCR image digest
```

Release metadata must retain enough information to recover this relationship.

## 7. Persistent data boundary

Home Assistant App backups are for installation-specific state, not reproducible application artifacts.

Persistent data may contain things such as:

```text
/data/options.json
/data/state.json
/data/recent_results.json
/data/servers.json
/data/installation_id
/data/installation_token
/data/telemetry_state.json
```

when those files are actually required by the product.

Do not move reproducible application content into `/data` merely to preserve it across upgrades.

Forbidden examples:

```text
Python virtualenv
pip cache
build cache
application binaries
container layers
downloaded dependency trees
temporary files
```

Principle:

> Everything reproducible from the immutable released artifact belongs to the artifact.
>
> Everything unique to one installation and required for recovery belongs to persistent state.

## 8. Backup acceptance

After migrating each Home Assistant App to registry delivery:

1. install the production App from the DigitalHouses App repository;
2. create a Full Backup;
3. inspect the App backup;
4. confirm installation-specific persistent state is present;
5. confirm a large locally built application image is not embedded in the App backup.

The acceptance criterion is not a fixed total Home Assistant backup size.

The criterion is:

```text
A DigitalHouses App backup does not contain a ~30–40 MB locally built
application image when the released image is recoverable from the
production registry.
```

## 9. Disaster-recovery acceptance

The decisive restore test must prove historical-version recovery.

Example:

```text
release Recorder 0.1.9
    ↓
install 0.1.9
    ↓
create backup
    ↓
release 0.1.10
    ↓
restore the old backup onto a clean supported Home Assistant system
    ↓
Supervisor can recover the required released image
    ↓
persistent data is restored
    ↓
installation identity is preserved
```

The test must prove that a newer current release does not make an older valid backup unrecoverable.

Old release images must therefore not be routinely deleted merely because a newer version exists.

---

# Part II — Shared DigitalHouses telemetry

## 10. One telemetry architecture

All products use one service:

```text
PVE Agent ─────────┐
Plex Agent ────────┤
Recorder App ──────┼── HTTPS ──> telemetry.digitalhouses.vip
Speedtest App ─────┤
Backblaze App ──────┘
```

All products use one wire contract:

[DigitalHouses Telemetry Protocol v1](TELEMETRY_PROTOCOL_V1.md)

All products use one privacy/consent model:

[DigitalHouses Product Telemetry Policy](PRODUCT_TELEMETRY_POLICY.md)

Product-specific implementation work follows:

[DigitalHouses Telemetry Implementation Guide](TELEMETRY_IMPLEMENTATION_GUIDE.md)

Product-specific telemetry protocols are prohibited unless a future standard explicitly introduces them.

## 11. Telemetry defaults

Every product must expose telemetry as an explicit opt-in.

Default:

```text
telemetry_enabled = false
```

Disabled means no telemetry HTTP requests.

Telemetry-server failure must never affect core product operation.

## 12. Installation identity

Every product installation gets its own persistent:

```text
installation_id
installation_token
```

The ID is UUIDv4.

The token is a cryptographically secure per-installation secret of at least 256 bits.

For Home Assistant Apps:

```text
/data/installation_id
/data/installation_token
```

or an equivalent persistent representation under `/data`.

For Linux Agents:

```text
/var/lib/digitalhouses/<product>/installation_id
/var/lib/digitalhouses/<product>/installation_token
```

or an equivalent product state file in the same persistent hierarchy.

Identity must survive restart, upgrade, and supported restore.

## 13. Minimal telemetry data

Protocol v1 heartbeat contains only:

```json
{
  "schema": 1,
  "telemetry_policy_version": 1,
  "installation_id": "550e8400-e29b-41d4-a716-446655440000",
  "product": "digitalhouses_recorder_app",
  "version": "0.1.9"
}
```

The client does not send country.

The server derives country and retains only the ISO country code.

No hostname, customer/site identity, Home Assistant UUID, network inventory, device inventory, MQTT configuration, email, username, city, coordinates, or serial-number data is part of protocol v1.

## 14. Heartbeat behavior

Normal cadence:

```text
1 heartbeat / 24h
```

with jitter, recommended:

```text
24h ± 30 min
```

An additional best-effort heartbeat is allowed after:

- telemetry is enabled;
- a successful upgrade to a new product version.

The scheduling implementation must avoid restart storms.

No heartbeat may be tied to each normal monitoring cycle.

## 15. Telemetry terminology

Because telemetry is voluntary, the telemetry service cannot know the complete installed base.

Reports must use terms such as:

```text
observed installations
telemetry-enabled installations
active telemetry installations
```

Do not call these numbers:

```text
users
total installations
complete installed base
```

Required windows:

```text
active 24h
active 7d
active 30d
```

Version and country adoption views normally use active 7d.

## 16. History retention and deletion

Current production behavior retains accepted heartbeat history without automatic time-based cleanup so long-term adoption/version/country dynamics remain available.

History is removed when:

- the installation performs authenticated deletion; or
- a future repository-level policy/protocol revision introduces retention.

Every implementation must support the shared authenticated deletion protocol.

Authenticated deletion removes the installation credential record and its retained heartbeat history.

`installation_id` is not an authentication secret.

## 17. Privacy wording

Do not describe protocol v1 as fully anonymous.

The persistent random installation ID is a pseudonymous identifier, and the request source IP is necessarily processed in transit even when it is not retained.

User-facing and policy wording must accurately describe:

- opt-in behavior;
- transmitted fields;
- server-derived country;
- IP non-retention across the complete controlled request path;
- retention;
- deletion;
- operator/controller identity.

Public legal wording requires legal review before general telemetry activation.

---

# Part III — Release automation

## 18. Required release pipeline

For every production release, shared release tooling must validate:

```text
1. requested product identifier is canonical
2. product source version matches requested version
3. CHANGELOG contains the release
4. canonical release tag is valid and unused
5. release version is newer than prior release versions
```

For Home Assistant Apps it must additionally:

```text
6. build image from the exact release source
7. publish GHCR :version
8. resolve and record image digest
9. verify package version / image version / release tag / commit relationship
10. publish GitHub Release and retain artifact provenance
```

Exact ordering may be implemented transactionally to avoid publishing a partial release, but the final successful release must satisfy the complete contract.

If any verification fails, the release is incomplete and must not be represented as a valid production release.

## 19. Release record

A completed Home Assistant App release must be able to identify at least:

```text
Product:
Version:
Release tag:
Commit SHA:
GitHub Release:
Image:
Image digest:
CI:
```

A Linux Agent release does not require a container image unless its delivery model is explicitly changed by a separate architecture decision.

---

# Part IV — Required tests

## 20. Shared telemetry tests

At minimum:

```text
fresh install -> new UUID/token created
restart -> same identity
upgrade -> same identity, new version reported
telemetry disabled -> no telemetry HTTP requests
telemetry enabled -> heartbeat sent
server unavailable -> product remains operational
repeated heartbeat -> a new observation is appended for the same installation
version update -> later heartbeat reports new version without changing installation identity
server timestamp -> received_at is generated by server
country -> derived by server, not client
IP -> absent from telemetry database
unknown product -> rejected
invalid UUID -> rejected
wrong installation token -> rejected
delete with valid token -> installation and heartbeat history removed
delete with ID only/wrong token -> rejected
history -> retained until authenticated deletion or future repository-level retention policy
```

## 21. Home Assistant App tests

For Recorder and Speedtest:

```text
production repository install succeeds
published versioned image is used
image tag matches product version
image digest is recorded
Full Backup contains persistent installation state
Full Backup does not embed a large local application image
restore recovers required released App version
installation identity survives backup/restore
historical backup remains restorable after a newer release exists
```

## 22. Release-contract tests

Repository validation must eventually enforce the architecture mechanically.

At minimum, automated checks should detect:

- production use of `latest`;
- App version/image-release mismatch;
- missing release provenance;
- unsupported product identifiers;
- telemetry default changed to enabled;
- protocol payload drift without protocol/policy update;
- missing mandatory telemetry tests in participating products where practical.

Policy without enforcement is considered incomplete implementation.

---

# Part V — Rollout

## 23. Initial rollout boundaries

The first immutable-delivery releases should contain only the delivery/backup migration plus required release tooling changes.

Current policy-adoption baselines make the natural first candidates:

```text
Recorder App: newer than 0.1.8
Speedtest App: newer than 1.2.1
```

The exact release versions must still follow the current product changelogs and release policy.

Telemetry should be introduced in subsequent product releases after the common telemetry server and protocol are ready.

## 24. Definition of done

This architecture is implemented only when all of the following are true:

```text
Home Assistant Apps:
- delivered from versioned GHCR artifacts
- backed by exact digest provenance
- installable from the DigitalHouses App repository
- no longer duplicate locally built application images into normal backups
- historical released images remain recoverable

All participating products:
- implement opt-in telemetry with default OFF
- use the same protocol and semantics
- preserve installation identity correctly
- tolerate telemetry failure completely

Telemetry service:
- stores minimum required installation credential data
- stores append-only heartbeat observations with server timestamps
- derives only country
- does not retain source IP in the telemetry database
- supports activity/version/country/history views
- has no automatic time-based retention cleanup under the current policy
- supports authenticated deletion of installation + heartbeat history
- exposes no remote-management channel

Repository:
- release and validation tooling enforce these contracts
- standards and implementation remain synchronized
```

Any product-specific implementation that produces the same required external contract may differ internally, but it must not weaken these guarantees.
