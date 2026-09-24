# DigitalHouses Repository Governance

This document defines repository-level Git workflow for `DigitalHouses/home-assistant-apps`.

Product implementation decisions remain owned by the corresponding product project and product documentation.

## 1. Canonical branch

`main` is the canonical repository branch and the source of truth for released and reusable code.

Changes should reach `main` through a pull request. Direct development on `main` is not part of the normal workflow.

## 2. Required validation

A pull request is ready to merge only when all current repository checks pass:

```text
Repository contract
PVE Agent
Plex Agent
Recorder App
Speedtest App
Backblaze App
```

The checks may evolve as products are added or removed, but the rule remains: the complete repository contract must be green before merge.

## 3. Merge strategy

The default merge strategy is a merge commit.

This preserves meaningful branch history, including TDD and implementation history, and keeps the integration boundary visible in `main`.

Do not squash or rewrite substantive product history unless there is an explicit reason to do so for that change.

## 4. Protection target for main

Repository settings should enforce the following controls for `main`:

- require a pull request before merge;
- require the repository CI checks to pass;
- prevent force pushes;
- prevent deletion of `main`;
- keep the branch up to date with its intended merge base when required by GitHub;
- do not require an artificial approval count when the repository is maintained by a single owner.

These settings enforce the workflow; this document remains the human-readable policy.

## 5. Branch naming

Use a branch name that states its purpose.

Preferred prefixes:

```text
feature/   product feature work
fix/       bug fix
design/    architecture/design work
chore/     repository maintenance
release/   temporary release preparation when needed
tdd/       temporary test-first implementation checkpoints
```

Branch names are working identifiers, not product or runtime API contracts.

## 6. Branch lifetime

Working branches are temporary.

After a pull request has been merged:

- delete the merged branch when its commits are fully reachable from `main`;
- keep tags and GitHub Releases as release provenance instead of long-lived release branches;
- do not keep TDD checkpoint branches merely as an archive when their history is already reachable from `main`.

Before deleting an old branch, compare it with `main`.

- `ahead = 0`: the branch has no unique commits and is safe for normal cleanup.
- `ahead > 0`: the branch contains Git history not reachable from `main`; do not delete it until those commits are reviewed.

A branch name such as `tmp`, `tdd`, `fix`, or `release` is never sufficient evidence by itself that deletion is safe.

## 7. Force push and history rewriting

Do not force-push `main`.

Avoid rewriting shared product branches after they are used for review, deployment, or release provenance. Prefer a new corrective commit.

Release tags are immutable and must never be moved to another commit.

## 8. Release provenance

Product releases follow [DigitalHouses Release Policy](RELEASE_POLICY.md).

The durable provenance chain is:

```text
product version
    ↓
main commit
    ↓
release tag
    ↓
GitHub Release
    ↓
exact commit SHA
```

Production systems are deployment targets. They do not replace GitHub as canonical source history.

## 9. Branch hygiene

Periodically audit repository branches against `main`.

The cleanup process should be mechanical:

1. enumerate branches;
2. compare every branch to `main`;
3. delete branches with no unique commits;
4. retain and review branches with unique commits;
5. never resolve ambiguity by branch name alone.

This keeps the public repository navigable without sacrificing unreconciled history.


## 10. Normative shared architecture

The following shared documents are normative repository contracts and apply to product development in their stated scope:

- [DigitalHouses Application Standard](DIGITALHOUSES_APP_STANDARD.md)
- [DigitalHouses Release Policy](RELEASE_POLICY.md)
- [DigitalHouses Immutable Delivery, Compact Backup and Telemetry Standard](IMMUTABLE_DELIVERY_AND_TELEMETRY_STANDARD.md)
- [DigitalHouses Product Telemetry Policy](PRODUCT_TELEMETRY_POLICY.md)
- [DigitalHouses Telemetry Protocol v1](TELEMETRY_PROTOCOL_V1.md)
- [DigitalHouses Telemetry Implementation Guide](TELEMETRY_IMPLEMENTATION_GUIDE.md)

Developers must implement product changes consistently with these contracts.

Product-specific code or documentation may add stricter requirements, but must not silently weaken or contradict a shared normative contract.

When a shared architecture contract changes intentionally, update the normative document and the corresponding validation, workflow, tests, and affected product implementations together.

A product is not considered migrated to a new shared contract merely because documentation was added. Repository validation and product acceptance tests must eventually enforce the contract mechanically.
