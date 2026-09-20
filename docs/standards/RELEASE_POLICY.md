# DigitalHouses Release Policy

Status: active for releases created after adoption of this policy.

This repository is a monorepo. Each DigitalHouses product has an independent version and release lifecycle.

## 1. Product release identifiers

Public release identifiers use the public product name, not an internal runtime identifier.

| Product | Release identifier |
| --- | --- |
| DigitalHouses PVE Agent | `digitalhouses_pve_agent` |
| DigitalHouses Plex Agent | `digitalhouses_plex_agent` |
| DigitalHouses Recorder App | `digitalhouses_recorder_app` |
| DigitalHouses Speedtest App | `digitalhouses_speedtest_app` |

These identifiers describe GitHub release provenance only. They do not require runtime service names, MQTT identifiers, Home Assistant slugs, filesystem paths, or other installed identities to change.

## 2. Version source of truth

Each product owns its own version.

- Linux agents use their product `VERSION` file as the release version source of truth.
- Home Assistant Apps use the version declared by the App package contract, including `config.yaml`, with all required duplicated version fields kept consistent by repository validation.
- The repository itself does not have a single global application version.

Versions follow semantic versioning in the form `MAJOR.MINOR.PATCH`. Pre-release identifiers may be used when appropriate, for example `1.0.0-alpha.1`, `1.0.0-beta.1`, or `1.0.0-rc.1`.

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

## 4. GitHub Releases

Every new public product release after adoption of this policy should have a GitHub Release associated with its release tag.

Release titles use:

```text
DigitalHouses <Product> v<version>
```

Release notes should summarize:

- user-visible changes;
- compatibility or migration requirements;
- important fixes;
- installation or update notes when they differ from the normal product instructions;
- the exact tagged source revision provided by GitHub.

The product changelog remains the detailed chronological product history. GitHub Releases are the public release boundary and provenance record.

## 5. Release flow

Normal release flow:

```text
development branch
    ↓
tests + version/changelog update
    ↓
pull request
    ↓
required repository CI
    ↓
merge to main
    ↓
tag the merge result on main
    ↓
publish GitHub Release
```

Do not create a public release tag from an unmerged feature, fix, design, TDD, or temporary branch.

## 6. Exact source identity

A human-readable version and an exact Git source identity are separate concepts.

Linux agents should continue to expose, where supported:

```text
Release version: <product version>
Source: <git tag/ref>
Build commit: <full commit SHA>
```

The commit SHA is the immutable source revision. A tag provides the human-readable release boundary.

## 7. Historical tags and releases

Existing historical tags are retained unchanged. They are not renamed, moved, or recreated under the new convention.

At the time this policy was adopted, historical PVE tags existed under the earlier `dh_pve_app-...` convention and no GitHub Releases had been published.

Do not fabricate retroactive releases merely to make old history look uniform. The new convention starts with future releases. Historical provenance remains valid in its original form.

## 8. Independent product releases

A change to one product does not require version bumps or releases for unrelated products.

A single repository commit may contain multiple product release changes only when intentionally coordinated. In that case, each released product receives its own tag and GitHub Release.
