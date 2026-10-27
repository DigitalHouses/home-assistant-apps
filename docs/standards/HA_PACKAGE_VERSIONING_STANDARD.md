# Home Assistant YAML Package Versioning Standard

**Status:** Normative repository policy  
**Effective:** 2026-10-27  
**Scope:** DigitalHouses-maintained HA package YAML files, including PVE Agent helpers and every local notification/locale variant.

## Required package metadata

Every new or revised distributable package MUST include the following YAML comments near the start of the exact file delivered to Home Assistant:

```yaml
# DH-Package: dh_pve_agent_package
# DH-Package-Version: 1.0.0
# DH-Package-Date: 2026-10-27
```

- `DH-Package` is the stable, unique package identity (prefer its top-level YAML key).
- `DH-Package-Version` follows `MAJOR.MINOR.PATCH`, independently of the Python App/Agent `VERSION`.
- `DH-Package-Date` is the release date of **this package revision**, formatted `YYYY-MM-DD`.
- Locale and delivery variants are separate packages and have **independent** version histories.
- The optional `DH-Compatible-Agent` comment MAY indicate a version range **only when tested**. Do not infer compatibility from similar filenames or the installed Agent version.
- Metadata stays in comments: no new HA entities, changing package keys, or extra runtime configuration just for version visibility.

## Version increment rules

Change **both** `DH-Package-Version` and `DH-Package-Date` on each newly released revision.

- PATCH: bug fixes, corrected notifications, presentation, documentation/comments or formatting.
- MINOR: backward-compatible new events, helpers or automations.
- MAJOR: incompatible event contracts, renamed/removed HA identifiers, or breaking migration requirements.

An Agent update without package changes does **not** change the package version. Release notes and change reports MUST distinguish Agent version and versions of modified HA packages.

## Comparison and diagnostics

Compare the **actual installed YAML files** for each site. Record the installed Agent version and each package's `DH-Package-Version` / `DH-Package-Date` separately. If a file has no header, identify it as **unversioned legacy**; do not guess when it was released based on its filename or an Agent version.

Keep stable package filenames across compatible updates. Installers, examples and copy instructions MUST preserve the metadata comments. New or revised package files without the required header are noncompliant. Changes should be checked in CI for header presence and valid format; a repository file and its changed release metadata must be reviewed together.

## Existing installations

Existing unversioned packages need not be rewritten in place just to satisfy this policy. Assign an initial package revision and date at the next controlled package change, after comparing that site's actual file. The date identifies the **new baseline release**, not the historical origin of the legacy file. Never claim compatibility with a specific Agent version without a validated test.

This policy does not change UPS/NUT safety logic or the contract for localized notification rendering.
