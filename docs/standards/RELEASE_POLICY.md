# DigitalHouses Release Policy

Status: active for releases created after adoption of this policy.

This policy applies to products in the `DigitalHouses/home-assistant-apps` repository.

`DigitalHouses/digitalhouses-website` is a separate private repository and is explicitly out of scope.

This repository is a monorepo. Each DigitalHouses product has an independent version, release lifecycle, and delivery model.

## 1. Product release identifiers

Public release identifiers use the public product name, not an internal runtime identifier.

| Product | Release identifier |
| --- | --- |
| DigitalHouses PVE Agent | `digitalhouses_pve_agent` |
| DigitalHouses Plex Agent | `digitalhouses_plex_agent` |
| DigitalHouses Recorder App | `digitalhouses_recorder_app` |
| DigitalHouses Speedtest App | `digitalhouses_speedtest_app` |

Release identifiers describe GitHub release provenance only.

They do not require runtime identities to change. In particular, adopting or changing a release identifier must not by itself rename:

- Linux service names;
- Home Assistant App slugs;
- repository directories;
- filesystem paths;
- MQTT topics, device identifiers, or unique IDs;
- Home Assistant entity IDs;
- other installed or compatibility-sensitive identities.

A runtime identity may change only through a separate product-specific compatibility decision.

## 2. Version source of truth

Each product owns its own Semantic Version.

Stable production releases use:

```text
MAJOR.MINOR.PATCH
```

When appropriate, Semantic Versioning prerelease identifiers may be used, for example:

```text
1.0.0-alpha.1
1.0.0-beta.1
1.0.0-rc.1
```

A prerelease version is published as a GitHub prerelease.

Version source of truth depends on product type:

- Linux agents use their product `VERSION` file.
- Home Assistant Apps use the version declared by the App package contract, including `config.yaml`, with all required duplicated version fields kept consistent by repository validation.
- The repository itself does not have a single global application version.

The product version, matching `CHANGELOG.md` section, release tag, and GitHub Release metadata must describe the same release.

## 3. Tag format

New release tags use:

```text
<release_identifier>-v<version>
```

Examples:

```text
digitalhouses_pve_agent-v0.6.0
digitalhouses_plex_agent-v0.3.0
digitalhouses_recorder_app-v0.2.0
digitalhouses_speedtest_app-v1.3.0
```

A release tag must point to the commit on `main` that contains the released product version and corresponding changelog entry.

Tags are immutable release provenance. Never move, rewrite, or reuse an existing release tag.

If a released version is defective, publish a newer version. Do not replace the source behind an existing release tag.

## 4. GitHub Releases

Every new public product release after adoption of this policy must have a GitHub Release associated with its release tag.

Release titles use:

```text
DigitalHouses <Product> v<version>
```

Release notes are taken from the matching product changelog section and should summarize:

- user-visible changes;
- compatibility or migration requirements;
- important fixes;
- installation or update notes when they differ from the normal product instructions.

The product changelog remains the detailed chronological product history.

GitHub Releases are the public release boundary and provenance record.

## 5. Release flow

Normal release flow:

```text
development branch
    ↓
implementation + tests
    ↓
version/changelog update
    ↓
pull request
    ↓
required repository CI
    ↓
merge to main
    ↓
Actions → Release product
    ↓
validated tag + GitHub Release
    ↓
product-specific production delivery
```

Do not create a public release tag from an unmerged feature, fix, design, TDD, or temporary branch.

A successful merge or GREEN CI result is not by itself a production release. A production release boundary exists only after the canonical release tag and GitHub Release have been published.

## 6. Exact source identity

A product version, release tag, and exact Git commit are related but distinct identities.

The canonical relationship is:

```text
Product version
    ↕
Release tag
    ↓
Exact commit SHA
```

The release tag is the primary human-readable release identifier.

The full commit SHA is the exact technical source identity used for audit, diagnostics, and verification.

Where supported, installed products should expose or retain:

```text
Release version: <product version>
Source: <release tag/ref>
Build commit: <full commit SHA>
```

The SHA must not replace the canonical release tag in normal production instructions when the product delivery model supports direct tag-based deployment.

## 7. Production delivery contract

Release identity and delivery mechanism are separate concepts.

### 7.1 Linux Agents

Production deployment of a Linux Agent must use the canonical release tag as the source ref.

Normal production deployment must not use:

- `main`;
- a development branch;
- a temporary branch;
- an arbitrary commit SHA as the operator-facing deployment ref.

The installer or deployment mechanism must resolve the release tag to the exact commit SHA and retain enough metadata to report, at minimum:

```text
Version: <product version>
Source: <release tag>
Commit: <full commit SHA>
```

The resolved SHA is verification metadata. The release tag remains the canonical production deployment ref.

### 7.2 Home Assistant Apps

For a Home Assistant App, the production version must correspond to a published canonical release tag and GitHub Release.

The tag and GitHub Release define release provenance:

```text
App version
    ↕
Release tag
    ↓
Exact main commit
```

The current Home Assistant App repository delivery mechanism may distribute an App from repository state and its package version rather than installing source directly from the Git release tag.

Therefore, until an immutable release artifact is used, do not claim that a deployed Home Assistant App was physically built from the release tag solely because the matching tag and GitHub Release exist.

The required current contract is:

- the App version in the package source matches the released version;
- the release tag points to the exact `main` commit containing that version;
- the GitHub Release is associated with that tag;
- repository validation and release validation pass before publication.

The target architecture for Home Assistant Apps is an immutable container artifact built from the exact released source and linked to:

```text
Version
Release tag
Exact commit SHA
Immutable container artifact
```

When that delivery model is implemented, the release workflow and App metadata must preserve this provenance end to end. Prefer immutable artifact identity, such as an image digest, over a mutable container tag when exact artifact pinning is available.

## 8. Historical tags and adoption baselines

Existing historical tags are retained unchanged. They are not renamed, moved, or recreated under the new convention.

At the time this policy was adopted, historical PVE tags existed under the earlier `dh_pve_app-...` convention and no GitHub Releases had been published.

The adoption baselines are:

| Product | Baseline |
| --- | ---: |
| DigitalHouses PVE Agent | `0.5.6` |
| DigitalHouses Plex Agent | `0.2.2` |
| DigitalHouses Recorder App | `0.1.8` |
| DigitalHouses Speedtest App | `1.2.1` |

The first tag under the new convention for each product must be newer than its baseline.

Do not fabricate retroactive releases merely to make old history look uniform. Historical provenance remains valid in its original form.

## 9. Independent product releases

A change to one product does not require version bumps or releases for unrelated products.

A single repository commit may contain multiple product release changes only when intentionally coordinated. In that case, each released product receives its own tag and GitHub Release.

A shared commit does not create a shared product version.

## 10. Supported release mechanism

New releases are published through the repository workflow:

```text
Actions → Release product → Run workflow
```

The workflow must be run from `main` and accepts exactly two inputs:

- product release identifier;
- exact Semantic Version already present on `main`.

Before publishing, the workflow validates:

- the complete repository contract;
- the requested Semantic Version;
- that the version is newer than the policy-adoption baseline;
- that the product source version exactly matches the requested version;
- that any `Unreleased` changelog section is empty;
- that a non-empty changelog section exists for the requested version;
- that the new-format tag does not already exist;
- that the requested version is newer than every existing new-format tag for that product.

After validation, the workflow creates the tag and GitHub Release from the exact checked-out `main` commit and verifies that the published tag resolves back to that commit.

Manual creation of new-format release tags is reserved for explicit recovery work.

## 11. Policy enforcement

This document is the normative repository release policy.

Repository tooling, including release validation and GitHub Actions workflows, implements this policy and must not contradict it.

In particular:

```text
RELEASE_POLICY.md
        ↓
release validation
        ↓
GitHub Actions release workflow
        ↓
product-specific delivery
```

If release tooling and this policy disagree, treat the mismatch as a repository defect to be corrected. Do not bypass the policy merely because the current tooling permits an inconsistent action.

A change that intentionally modifies the release contract must update this policy and the corresponding validation/workflow behavior together.

Where practical, repository settings or GitHub rulesets should technically protect canonical release tags from accidental rewrite or deletion. Process-level tag immutability remains mandatory even when platform enforcement is not yet configured.

## 12. Release completion record

A product release is considered operationally complete when its release record can identify at least:

```text
Product:
Version:
Release tag:
Commit SHA:
GitHub Release:
CI:
```

For Linux Agents, production deployment instructions should use the release tag.

For Home Assistant Apps, the record must distinguish release provenance from the current delivery mechanism until immutable release artifacts are implemented.
