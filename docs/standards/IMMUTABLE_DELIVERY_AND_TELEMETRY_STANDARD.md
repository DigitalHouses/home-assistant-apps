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
digitalhouses_backblaze_app
digitalhouses_internet_app
```

The Home Assistant image/backup requirements apply only to Home Assistant Apps. The release identity and telemetry requirements apply to all participating products.

Deprecated products that are explicitly superseded by a separate canonical product are not required to retrofit new delivery or telemetry architecture solely for standards conformance. Their historical release/runtime contract remains frozen except for critical compatibility or security fixes.

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
required product heartbeat
   ↓
telemetry.digitalhouses.vip
   ↓
product / version / installation identity / country / activity
```

The architecture deliberately separates deployment from telemetry. A product must remain fully functional when telemetry delivery is unavailable or blocked.

## 2. Implementation order

Implementation is staged.

### Stage A — immutable Home Assistant App delivery

The initial immutable-delivery migration started with `digitalhouses_recorder_app`. DigitalHouses Speedtest App was later deprecated and superseded by Internet App, so it is excluded from retrofit work.

Required outcome:

- production Apps are installed from the DigitalHouses App repository;
- application code is delivered through versioned GHCR images;
- local-image backup duplication is removed;
- released image versions remain immutable and are retained according to repository artifact-retention policy.

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

Integrate the same telemetry client semantics into active supported products:

```text
digitalhouses_pve_agent
digitalhouses_plex_agent
digitalhouses_recorder_app
digitalhouses_backblaze_app
digitalhouses_internet_app
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

Released image versions must not be overwritten. Artifact retention is an operational/repository policy concern and is not a per-release backup acceptance requirement.

## 5. Home Assistant App image contract

A production Home Assistant App must reference the published image repository through its App package metadata.

The product version remains the version source of truth.

Conceptually:

```yaml
version: "0.1.9"
image: "ghcr.io/digitalhouses/digitalhouses_recorder_app"
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

1. install the current production App from the DigitalHouses App repository;
2. create a Home Assistant backup that includes the App;
3. inspect the App backup;
4. confirm installation-specific persistent state is present;
5. confirm a large locally built application image is not embedded in the App backup.

The acceptance criterion is not a fixed total Home Assistant backup size.

The criterion is:

```text
A DigitalHouses App backup contains installation-specific persistent state,
but does not duplicate the reproducible application image when that image is
delivered from the production registry.
```

## 9. Restore acceptance

Restore acceptance validates installation state recovery for the supported current production App lifecycle.

A product-level acceptance test should confirm that:

1. the App can be restored on a supported Home Assistant system;
2. the required published registry image can be obtained;
3. persistent `/data` state is restored;
4. installation identity and other documented persistent product state are preserved.

Restoring an older App release after a newer release has been published is **not** a mandatory immutable-delivery acceptance test.

Historical-version restore, downgrade and rollback testing are separate operational or migration procedures and should be required only when a specific product migration or recovery plan needs them.

This distinction keeps immutable artifact integrity separate from product-version rollback policy.

---

# Part II — Shared DigitalHouses telemetry

## 10. One telemetry architecture

All products use one service:

```text
PVE Agent ─────────┐
Plex Agent ────────┤
Recorder App ──────┼── HTTPS ──> telemetry.digitalhouses.vip
Backblaze App ─────┤
Internet App ──────┘
```

All products use one wire contract:

[DigitalHouses Telemetry Protocol v1](TELEMETRY_PROTOCOL_V1.md)

All products use one privacy/participation model:

[DigitalHouses Product Telemetry Policy](PRODUCT_TELEMETRY_POLICY.md)

Product-specific implementation work follows:

[DigitalHouses Telemetry Implementation Guide](TELEMETRY_IMPLEMENTATION_GUIDE.md)

Product-specific telemetry protocols are prohibited unless a future standard explicitly introduces them.

## 11. Telemetry defaults

Supported official DigitalHouses products use telemetry policy version 2.

Telemetry reporting is part of supported product operation **after explicit acceptance of the current telemetry/privacy terms**, and is not exposed as an ordinary runtime opt-in/opt-out configuration option.

Подтверждение выполняется **исключительно в конфигурации**: `telemetry_policy_acceptance: not_accepted|accept_v2` в Home Assistant App options; `[telemetry] policy_acceptance = "not_accepted"|"accept_v2"` в конфиге Linux Agent. По умолчанию подтверждения нет. `accept_v2` выбирается вручную после ознакомления с опубликованной редакцией. Ingress, дополнительный UI и MQTT-переключатели не требуются и не используются; это не опция отключения статистики. Принятую редакцию и время локально фиксирует сам продукт. Новая существенно изменённая редакция требует повторного явного принятия. Публичное включение остаётся под legal gate. Without acceptance, the supported product must not activate or send telemetry. Legacy telemetry-enabled settings are not proof of policy-v2 acceptance.

After acceptance, the client always schedules the minimal heartbeat defined by protocol v1. Telemetry-server failure, DNS failure, firewall blocking, timeout or rate limiting must never affect core product operation.

Legacy policy-v1 releases remain valid during migration and continue to be accepted by the server.

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
  "telemetry_policy_version": 2,
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

- a fresh installation;
- a successful upgrade to a new product version;
- authenticated deletion followed by local identity rotation.

The scheduling implementation must avoid restart storms.

No heartbeat may be tied to each normal monitoring cycle.

## 15. Telemetry terminology

Required reporting still cannot prove the complete installed base because an installation may be offline, blocked by network policy, modified, abandoned, or otherwise unable to reach the telemetry service.

Reports must use terms such as:

```text
observed installations
reporting installations
active installations
```

Do not call these numbers:

```text
users
guaranteed total installations
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

Authenticated deletion removes the installation credential record and its retained heartbeat history. Under telemetry policy version 2, the client then rotates its local installation ID/token. If the product remains in use, later reporting resumes under that fresh identity.

`installation_id` is not an authentication secret. Deletion is an erasure operation, not a telemetry opt-out.

## 17. Privacy wording

Do not describe protocol v1 as fully anonymous.

The persistent random installation ID is a pseudonymous identifier, and the request source IP is necessarily processed in transit even when it is not retained.

User-facing and policy wording must accurately describe:

- required telemetry participation for supported products;
- transmitted fields;
- server-derived country;
- IP non-retention across the complete controlled request path;
- retention;
- deletion and identity rotation;
- the fact that continued product use resumes reporting after deletion;
- operator/controller identity.

Public legal wording requires legal review before broad mandatory-telemetry distribution.

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
HA options / Agent config -> not_accepted by default; only explicit accept_v2 is acceptance
no separate Ingress / MQTT / web activation UI for acceptance
acceptance -> accepted_at and exact policy revision/hash are persisted
material policy revision -> new config acceptance is required
fresh install without acceptance -> no new telemetry identity, no heartbeat, consent-required/not-activated state
explicit acceptance -> accepted terms revision and timestamp persisted; new UUID/token created; telemetry schedules
legacy policy-v1 telemetry_enabled true/false -> does not imply policy-v2 acceptance
refusal or legally required withdrawal -> no future telemetry and no silent supported runtime continuation without required consent
accepted release -> no normal telemetry opt-out control in product config
restart -> same identity
upgrade -> same identity, new version reported
server unavailable/blocking -> product remains operational
repeated heartbeat -> a new observation is appended for the same installation
version update -> later heartbeat reports new version without changing installation identity
server timestamp -> received_at is generated by server
country -> derived by server, not client
IP -> absent from telemetry database
unknown product -> rejected
invalid UUID -> rejected
wrong installation token -> rejected
policy version 1 -> accepted during migration
policy version 2 -> accepted
unsupported policy version -> rejected
delete with valid token -> installation and heartbeat history removed
delete success -> client identity/token rotated
continued use after delete -> later report uses fresh identity
delete with ID only/wrong token -> rejected
history -> retained until authenticated deletion or future repository-level retention policy
```

## 21. Home Assistant App tests

For participating Home Assistant Apps:

```text
production repository install succeeds
published versioned image is used
image tag matches product version
image digest is recorded
backup contains persistent installation state
backup does not embed a large local application image
restore recovers persistent App state on a supported system
installation identity survives backup/restore
```

Historical-version restore after a newer release exists is not a general release-contract requirement. Add downgrade/rollback tests only where a product-specific migration or recovery procedure explicitly requires them.

## 22. Release-contract tests

Repository validation must eventually enforce the architecture mechanically.

At minimum, automated checks should detect:

- production use of `latest`;
- App version/image-release mismatch;
- missing release provenance;
- unsupported product identifiers;
- policy-v2 product still exposes a telemetry opt-out or sends the wrong telemetry policy version;
- protocol payload drift without protocol/policy update;
- missing mandatory telemetry tests in participating products where practical.

Policy without enforcement is considered incomplete implementation.

---

# Part V — Rollout

## 23. Initial rollout boundaries

The first immutable-delivery releases should contain only the delivery/backup migration plus required release tooling changes.

Current policy-adoption baselines made Recorder App the initial migration candidate.

DigitalHouses Speedtest App is now deprecated and superseded by DigitalHouses Internet App. It is intentionally excluded from further immutable-delivery and telemetry retrofit work; its existing release/runtime identity remains frozen for legacy installations.

The exact release versions must still follow the current product changelogs and release policy.

Telemetry policy v2 is introduced product by product after the shared server accepts both legacy policy v1 and current policy v2.

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
- implement required telemetry policy v2 with no product opt-out control
- use the same protocol and semantics
- preserve installation identity correctly across restart/upgrade/restore
- rotate identity after authenticated deletion
- tolerate telemetry failure or blocking completely

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
