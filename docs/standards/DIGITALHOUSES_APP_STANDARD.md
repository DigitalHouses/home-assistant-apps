# DigitalHouses Application Standard v1

**Status:** Approved
**Date:** 2026-09-09
**Scope:** All applications in `DigitalHouses/home-assistant-apps`

---

## 1. Purpose

`digitalhouses_*` is the common family of DigitalHouses applications. It is **not** synonymous with a Home Assistant OS add-on.

This standard defines:

- a common contract for every DigitalHouses application;
- explicit application types;
- type-specific contracts;
- application-specific compatibility contracts;
- repository-wide CI rules;
- templates for creating new applications;
- GitHub as the source of truth.

Initial supported application types:

```text
DigitalHouses Application Standard
├── Common contract
│
├── haos_addon
│
└── linux_agent
```

Current applications:

```text
digitalhouses_speedtest       -> haos_addon
digitalhouses_db_monitoring   -> haos_addon
```

Planned first `linux_agent`:

```text
digitalhouses_plex_monitoring -> linux_agent
```

---

## 2. Core principle

Every `digitalhouses_*` project must explicitly declare its application type.

Type detection must **never** be inferred from the presence of files such as `Dockerfile`, `config.yaml`, `install.sh`, or a systemd unit.

The declaration is stored in:

```text
digitalhouses.app
```

Example for a HAOS add-on:

```ini
type = haos_addon
```

Example for a Linux agent:

```ini
type = linux_agent
```

The declared type is part of the application's stable repository contract.

### `digitalhouses.app` file format

`digitalhouses.app` is a **flat UTF-8 metadata file using `key = value` syntax**.

It is intentionally **not** an INI file and must not require section headers.

Initial mandatory key:

```text
type = <application_type>
```

Examples:

```text
type = haos_addon
```

```text
type = linux_agent
```

Parsing rules:

- UTF-8 text;
- one `key = value` pair per line;
- surrounding whitespace around keys and values is ignored;
- blank lines are allowed;
- lines beginning with `#` are comments;
- duplicate keys are invalid;
- unknown mandatory application types are invalid;
- validators must parse this file explicitly and must not use INI section semantics.

---

## 3. Repository model

```text
home-assistant-apps/
├── .github/
│   └── workflows/
├── docs/
│   └── DIGITALHOUSES_APP_STANDARD.md
├── scripts/
│   ├── validate_repository.py
│   └── validators/
│       ├── common.py
│       ├── types/
│       │   ├── haos_addon.py
│       │   └── linux_agent.py
│       └── apps/
│           ├── speedtest.py
│           ├── db_monitoring.py
│           └── plex_monitoring.py
├── templates/
│   ├── haos_addon/
│   └── linux_agent/
├── digitalhouses_speedtest/
├── digitalhouses_db_monitoring/
├── digitalhouses_plex_monitoring/
├── repository.yaml
├── README.md
└── LICENSE
```

GitHub is the authoritative source for:

- this standard;
- application source;
- release history;
- templates;
- CI rules;
- compatibility contracts;
- installers and deployment artifacts.

---

## 4. Validation flow

Repository validation follows this sequence:

```text
discover digitalhouses_*
        ↓
read digitalhouses.app
        ↓
run common checks
        ↓
run type-specific checks
        ↓
run app-specific regression contract
```

Unknown or missing application types must fail validation.

The validator must not silently guess an application type.

---

# Part I — Common contract

## 5. Common naming contract

Every application directory uses:

```text
digitalhouses_<app_name>
```

Examples:

```text
digitalhouses_speedtest
digitalhouses_db_monitoring
digitalhouses_plex_monitoring
```

The directory name is the canonical repository identifier of the application.

Stable public identifiers such as MQTT topics, device identifiers, entity IDs, service names, or configuration paths become compatibility interfaces once released and must be protected by application-specific regression checks where appropriate.

---

## 6. Common mandatory files

Every `digitalhouses_*` application must contain at least:

```text
digitalhouses_<app_name>/
├── digitalhouses.app
├── README.md
├── CHANGELOG.md
└── tests/
    └── test_*.py
```

Additional mandatory files are defined by the application type.

---

## 7. Common documentation contract

### `README.md`

Must describe the current application, including where applicable:

- purpose;
- architecture;
- supported environment;
- installation summary;
- upgrade model;
- main capabilities;
- compatibility expectations;
- link to deeper documentation if present.

The README must describe the current product, not only its first historical version.

### `CHANGELOG.md`

Must contain:

- newest release first;
- one section per published version;
- externally relevant changes;
- compatibility-impacting changes.

A release must have a matching changelog section according to the version contract of its application type.

### Additional documentation

`DOCS.md` or a `docs/` directory may be required by a type-specific contract.

---

## 8. Common test standard

Every application must have automated tests.

Tests for one application must pass together as one suite.

A test that passes only when executed alone is considered broken.

Tests must not permanently pollute shared interpreter or process state such as:

```text
sys.modules
sys.path
os.environ
current working directory
temporary global registries
```

Temporary changes must be restored using fixtures, context managers, patch helpers, setup/teardown logic, or process isolation when justified.

Tests should cover, where applicable:

- configuration parsing;
- data transformation;
- protocol payloads;
- persistence;
- scheduling;
- commands;
- installation/update behavior;
- adapters;
- failure handling;
- compatibility contracts.

---

## 9. Common CI contract

A green repository status must mean that **every published DigitalHouses application** passed all checks required by:

1. the common contract;
2. its declared type contract;
3. its application-specific regression contract.

CI must never present a repository-wide green result while silently skipping one application family.

---

## 10. Common compatibility contract

Generic repository rules and application-specific compatibility rules are separate concerns.

### Standard

Defines:

> What every application of a given class must look like and how it must be validated.

### Compatibility contract

Defines:

> Which stable public interfaces of one specific application must not change accidentally.

Examples:

- MQTT topics;
- Home Assistant entity IDs;
- device IDs;
- systemd service names;
- Linux configuration paths;
- state file names;
- command topics;
- payload schemas.

Application-specific checks must not be mixed into generic validation logic.

---

## 11. Common private-dependency rule

Reusable public DigitalHouses application code must not depend on private site-specific mechanisms.

Examples of forbidden implicit dependencies:

- `write2log`;
- customer-specific scripts;
- private notification services;
- fixed customer IP addresses;
- private Home Assistant entity names;
- undocumented local filesystem paths;
- credentials;
- private router/ONT vendor bindings.

Project-specific integration belongs in explicit local adapters, passports, configuration files, or notification packages.

---

## 12. Common source-of-truth rule

GitHub is the source of truth.

Production installations, HAOS instances, VMs, and LXCs are deployment targets, not canonical source repositories.

Changes intended to persist across installations must be represented in GitHub.

Manual production-only edits must either:

- be intentionally local configuration; or
- be returned to GitHub before they are treated as part of the product.

---

# Part II — `haos_addon` contract

## 13. HAOS add-on structure

A `haos_addon` must use:

```text
digitalhouses_<app_name>/
├── digitalhouses.app
├── config.yaml
├── Dockerfile
├── README.md
├── DOCS.md
├── CHANGELOG.md
├── rootfs/
│   ├── run.sh
│   └── app/
│       └── ...
├── tests/
│   └── test_*.py
├── translations/
│   ├── en.yaml
│   └── ru.yaml
├── images/
│   └── ...
└── examples/                  # optional
    ├── packages/
    └── lovelace/
```

`digitalhouses.app` must contain:

```ini
type = haos_addon
```

---

## 14. HAOS naming contract

`config.yaml -> slug` must exactly match the application directory name.

Example:

```text
directory: digitalhouses_speedtest
slug:      digitalhouses_speedtest
```

Unless explicitly documented otherwise, MQTT namespace should follow:

```text
DigitalHouses/Global/<app_name>
```

---

## 15. HAOS version contract

For `haos_addon`, `config.yaml` is the authoritative release-version source.

The same version must appear in:

1. `config.yaml`
2. Dockerfile default `ARG BUILD_VERSION`
3. matching section in `CHANGELOG.md`

Example:

```yaml
version: 1.2.0
```

```dockerfile
ARG BUILD_VERSION="1.2.0"
```

```markdown
## 1.2.0
```

CI must fail when these values differ.

Runtime source should receive the version through `APP_VERSION`.

A local source fallback may use a suffix such as:

```text
1.2.0-local
```

but must not become a second release-version authority.

---

## 16. HAOS Dockerfile contract

Each HAOS add-on Dockerfile must:

- use a Home Assistant App-compatible base image;
- declare `ARG BUILD_VERSION`;
- declare `ARG BUILD_ARCH`;
- expose `APP_VERSION`;
- set Home Assistant App labels;
- install runtime dependencies explicitly;
- copy `rootfs/`;
- ensure `/run.sh` is executable;
- compile Python source during image build;
- use:

```dockerfile
CMD ["/run.sh"]
```

Published architectures must match:

```text
config.yaml -> arch
```

Future CI must perform Docker build smoke tests for every published architecture.

---

## 17. HAOS `run.sh` contract

`rootfs/run.sh` must:

- have a valid shell interpreter;
- fail clearly on unrecoverable startup errors;
- use Bashio when Supervisor services are required;
- resolve runtime service configuration;
- hand control to the main process with `exec`;
- avoid application business logic that belongs in Python.

CI must run:

```bash
bash -n rootfs/run.sh
```

---

## 18. HAOS Python contract

Application code lives under:

```text
rootfs/app/
```

Rules:

- modules should have clear responsibilities;
- configuration parsing should be separated from runtime orchestration;
- protocol/discovery definitions should be separated from metric collection where practical;
- adapters should be isolated where practical;
- persistent application state belongs under `/data`;
- global reusable code must not embed site-local bindings.

---

## 19. HAOS translation contract

Mandatory:

```text
translations/en.yaml
translations/ru.yaml
```

Both files must be valid YAML.

English is the primary public translation.

Russian is mandatory for DigitalHouses-maintained HAOS add-ons.

---

## 20. HAOS examples contract

`examples/` is optional.

Reusable examples must not introduce private site dependencies.

For Internet/Speedtest architecture:

```text
global = common reusable logic
local  = site-specific passport / bindings
```

Global packages must operate through normalized abstractions rather than vendor-specific entities.

---

## 21. HAOS CI checks

For every `haos_addon`, CI must run:

```text
Common checks
HAOS type contract
Python compile
Unit tests
run.sh shell syntax
Docker/config/version checks
Translation validation
App-specific regression contract
```

Python compile check:

```bash
python -m compileall -q \
  digitalhouses_<app>/rootfs/app \
  digitalhouses_<app>/tests
```

Canonical tests:

```bash
python -m unittest discover -s digitalhouses_<app>/tests -v
```

Future:

```text
Docker build smoke-test matrix by published architecture
```

---

# Part III — `linux_agent` contract

## 22. Linux agent purpose

A `linux_agent` is a native Linux application installed directly into a VM, LXC, or Linux host.

It is not a HAOS add-on and must not require HAOS Supervisor, HAOS add-on metadata, or Home Assistant add-on container structure.

The first DigitalHouses application of this type is:

```text
digitalhouses_plex_monitoring
```

---

## 23. Linux agent structure

Base structure:

```text
digitalhouses_<app_name>/
├── digitalhouses.app
├── README.md
├── CHANGELOG.md
├── VERSION
├── install.sh
├── app/
│   └── ...
├── systemd/
│   └── <app-name>.service
├── tests/
│   └── test_*.py
└── examples/                  # optional / conditional
    └── <app-name>.conf.example
```

`digitalhouses.app` must contain:

```ini
type = linux_agent
```

`DOCS.md`, `images/`, or other support directories may be added when useful but are not mandatory for every Linux agent.

---

## 24. Linux agent canonical name

For the Linux-agent contract:

```text
<app-name>
```

means the application directory name.

Example:

```text
digitalhouses_plex_monitoring
```

Therefore the default service and configuration naming is:

```text
systemd/digitalhouses_plex_monitoring.service
/etc/digitalhouses_plex_monitoring/digitalhouses_plex_monitoring.conf
```

A deliberate exception must be documented and protected by the application's compatibility contract.

---

## 25. Linux agent version contract

For `linux_agent`, the authoritative release version is the root plain-text file:

```text
VERSION
```

Example:

```text
0.1.0
```

The same version must have a matching section in:

```text
CHANGELOG.md
```

Installer or runtime version reporting must read or receive this version rather than maintaining an independent hard-coded release version.

CI must fail when the version contract is inconsistent.

---

### Git source/build identity

`VERSION` remains the release version.

When a Linux agent is installed from a Git source such as `main`, the installed application must also preserve diagnostic source identity so that two installations with the same release version can still be distinguished.

At minimum, installed/runtime diagnostics must expose:

```text
Release version: <VERSION>
Source: <git branch or tag>
Build commit: <git commit SHA>
```

Example:

```text
Release version: 0.1.0
Source: main
Build commit: a8fee8b
```

Rules:

- release version comes only from `VERSION`;
- branch/tag identifies the Git source reference when available;
- commit SHA identifies the exact source revision;
- the installer must capture this identity at install/update time when installing from Git;
- runtime diagnostics should expose the stored identity without requiring the installed target to remain a live Git working tree;
- commit SHA should be stored in full where practical, though UI/log output may show an unambiguous short form;
- release/tag installations should preserve the tag name when available;
- CI or packaged builds may provide equivalent source/build metadata through build-time variables.

This identity is diagnostic metadata, not a replacement for semantic release versioning.

---
## 26. Linux agent filesystem contract

All `linux_agent` installations use the same canonical filesystem layout:

```text
/opt/digitalhouses/<app-name>/       application/source
/etc/<app-name>/<app-name>.conf      configuration
/var/lib/<app-name>/                 persistent/runtime state
journald                             logs
```

Example for Plex Monitoring:

```text
/opt/digitalhouses/digitalhouses_plex_monitoring/
/etc/digitalhouses_plex_monitoring/digitalhouses_plex_monitoring.conf
/var/lib/digitalhouses_plex_monitoring/
journald
```

Rules:

- application code and installed source live under `/opt/digitalhouses/<app-name>/`;
- operator-managed configuration lives under `/etc/<app-name>/`;
- persistent mutable application state lives under `/var/lib/<app-name>/`;
- services log to `journald` unless an application has a documented compatibility exception;
- installers must create required directories with appropriate permissions;
- application code must not treat the Git checkout itself as persistent runtime state;
- local configuration and runtime state must survive application upgrades.

A deliberate filesystem-layout exception must be documented and protected by the application's compatibility contract.

---

## 27. Linux agent configuration contract

Linux agents use native `.conf` configuration rather than YAML unless a specific application has an approved exception.

Canonical production path:

```text
/etc/<app-name>/<app-name>.conf
```

Example:

```text
/etc/digitalhouses_plex_monitoring/digitalhouses_plex_monitoring.conf
```

Rules:

- configuration extension is `.conf`;
- installer creates the configuration directory if needed;
- configuration files containing credentials or other secrets should use mode `0600` by default;
- mode `0640` is allowed when access is intentionally shared with a dedicated service group;
- broader permissions for secret-bearing configuration require explicit technical justification and documentation;
- an existing production `.conf` must **never** be overwritten during update;
- first install may create a configuration file from an example/template;
- configuration semantics must be documented in README or dedicated docs;
- secrets must not be committed to GitHub.

When configuration is required, the repository should provide:

```text
examples/<app-name>.conf.example
```

---

## 28. Linux agent installer contract

Every Linux agent must provide:

```text
install.sh
```

The installer is **idempotent**.

The same installation command is used for:

- first installation;
- reinstall;
- upgrade.

Running the installer repeatedly must converge on the intended installed state without destroying local configuration.

The installer must:

- detect or create required directories;
- install/update application files;
- install/update the systemd unit;
- capture and store Git source/build identity when installed from Git;
- preserve an existing `.conf`;
- create a first-run `.conf` only when absent and required;
- reload systemd when unit files change;
- enable the service when appropriate;
- restart or start the service in a controlled way;
- fail clearly when mandatory prerequisites are missing.

The installer must not require the operator to manually copy application source files after installation.

CI must run:

```bash
bash -n install.sh
```

---

## 29. Linux agent application contract

Application source lives under:

```text
app/
```

Rules:

- native Linux runtime;
- no dependency on HAOS Supervisor APIs;
- no assumption that `/config`, `/data`, or HAOS add-on filesystem conventions exist;
- runtime state and logs use appropriate Linux locations;
- system integration is explicit;
- site-specific values come from `.conf` or explicit adapters;
- reusable source must not contain customer-specific bindings.

Python agents should use clear module boundaries for configuration, collection, transport/publishing, persistence, and service orchestration where practical.

---

## 30. Linux agent systemd contract

Every Linux agent must provide at least one unit:

```text
systemd/<app-name>.service
```

The unit must:

- use deterministic executable paths;
- use the canonical configuration path where applicable;
- define a sensible restart policy;
- have correct dependency ordering;
- avoid embedding secrets;
- avoid machine-specific paths not created by the installer;
- run under a dedicated unprivileged service user by default;
- use `root` only when technically required, with the reason explicitly documented in the application README or dedicated documentation.

CI should validate systemd units with:

```bash
systemd-analyze verify systemd/*.service
```

where supported by the CI environment.

If additional units such as timers are used, they are part of the same type-specific validation.

---

## 31. Linux agent test contract

Canonical Python test command:

```bash
python -m unittest discover -s digitalhouses_<app>/tests -v
```

where the agent is Python-based.

Tests should cover, where applicable:

- configuration parsing;
- first-install behavior;
- update behavior;
- config preservation;
- service/unit generation assumptions;
- data collection;
- publishing;
- persistence;
- load-sensitive behavior;
- failure handling;
- compatibility contracts.

Installer behavior that can be tested without modifying the real host should use temporary directories or explicit test roots.

Tests must never damage the machine running CI.

---

## 32. Linux agent CI checks

For every `linux_agent`, CI must run:

```text
Common checks
Linux-agent type contract
Python compile
Unit tests
install.sh shell syntax
systemd unit checks
configuration/example checks
version checks
App-specific regression contract
```

For Python agents:

```bash
python -m compileall -q \
  digitalhouses_<app>/app \
  digitalhouses_<app>/tests
```

Installer:

```bash
bash -n digitalhouses_<app>/install.sh
```

Systemd:

```bash
systemd-analyze verify digitalhouses_<app>/systemd/*.service
```

when supported.

---

# Part IV — Validators and CI architecture

## 33. Generic repository validator

`validate_repository.py` must:

1. discover directories matching:

```text
digitalhouses_*
```

2. require and parse:

```text
digitalhouses.app
```

3. run common checks;

4. dispatch to the matching type validator;

5. invoke application-specific compatibility checks when defined.

Pseudo-flow:

```text
for app in discover("digitalhouses_*"):
    metadata = read("digitalhouses.app")
    validate_common(app, metadata)

    if metadata.type == "haos_addon":
        validate_haos_addon(app)
    elif metadata.type == "linux_agent":
        validate_linux_agent(app)
    else:
        fail("unknown application type")

    validate_app_regression(app)
```

No application type may be inferred indirectly.

---

## 34. Validator separation

Recommended structure:

```text
scripts/
└── validators/
    ├── common.py
    ├── types/
    │   ├── haos_addon.py
    │   └── linux_agent.py
    └── apps/
        ├── speedtest.py
        ├── db_monitoring.py
        └── plex_monitoring.py
```

Responsibilities:

### `common.py`

- directory naming;
- `digitalhouses.app`;
- common required files;
- common test presence;
- generic metadata parsing;
- common documentation checks.

### `types/haos_addon.py`

- `config.yaml`;
- Dockerfile;
- `rootfs/run.sh`;
- `rootfs/app/`;
- translations;
- HAOS version contract;
- architecture validation;
- HAOS-specific required files.

### `types/linux_agent.py`

- `VERSION`;
- `install.sh`;
- `app/`;
- `systemd/`;
- `.conf` convention;
- installer contract;
- systemd naming;
- Linux-agent version contract.

### `apps/*.py`

Stable application-specific interfaces.

---

## 35. CI architecture

Repository CI should conceptually look like:

```text
Repository contract
├── Common checks
│
├── HAOS add-ons
│   ├── Speedtest
│   │   ├── Python compile
│   │   ├── unit tests
│   │   ├── shell syntax
│   │   ├── Docker/config/version checks
│   │   └── app-specific regression
│   │
│   └── DB Monitoring
│       ├── Python compile
│       ├── unit tests
│       ├── shell syntax
│       ├── Docker/config/version checks
│       └── app-specific regression
│
└── Linux agents
    └── Plex Monitoring
        ├── Python compile
        ├── unit tests
        ├── install.sh syntax
        ├── systemd unit checks
        ├── config/example checks
        ├── version checks
        └── app-specific regression
```

Future HAOS build stage:

```text
Docker build smoke test
└── HAOS add-on × published architecture matrix
```

Linux agents do not enter the HAOS Docker-build matrix unless a specific agent explicitly adds a container distribution target in the future.

---

# Part V — Templates

## 36. Template structure

The repository must provide separate templates:

```text
templates/
├── haos_addon/
└── linux_agent/
```

There is no single generic filesystem template because the runtime models are intentionally different.

---

## 37. HAOS add-on template

```text
templates/haos_addon/
├── digitalhouses.app
├── config.yaml
├── Dockerfile
├── README.md
├── DOCS.md
├── CHANGELOG.md
├── rootfs/
│   ├── run.sh
│   └── app/
│       └── app.py
├── tests/
│   └── test_smoke.py
├── translations/
│   ├── en.yaml
│   └── ru.yaml
└── images/
```

Its metadata contains:

```ini
type = haos_addon
```

---

## 38. Linux agent template

```text
templates/linux_agent/
├── digitalhouses.app
├── README.md
├── CHANGELOG.md
├── VERSION
├── install.sh
├── app/
│   └── app.py
├── systemd/
│   └── digitalhouses_example.service
├── tests/
│   └── test_smoke.py
└── examples/
    └── digitalhouses_example.conf.example
```

Its metadata contains:

```ini
type = linux_agent
```

---

## 39. Template validation

Both templates must themselves pass generic validation for their declared type.

Templates are not production applications and therefore may use clearly documented placeholder identifiers.

The CI must prevent the templates from drifting away from the contracts they are meant to represent.

---

# Part VI — Application-specific compatibility contracts

## 40. `digitalhouses_speedtest`

Type:

```ini
type = haos_addon
```

App-specific regression contract includes at minimum:

- MQTT base topic;
- discovery device ID;
- legacy `unique_id` values;
- legacy default entity IDs;
- persistence filenames;
- required public package keys;
- local passport key;
- dashboard Sections structure.

Public/global examples must remain independent of local notification mechanisms and private hardware bindings.

---

## 41. `digitalhouses_db_monitoring`

Type:

```ini
type = haos_addon
```

App-specific regression contract includes at minimum:

- MQTT base topic;
- discovery device ID;
- stable metric entity IDs;
- refresh command topic;
- ranking payload schema;
- storage entity IDs.

All tests must pass together in one suite; test modules may not pollute one another through persistent `sys.modules` replacements.

---

## 42. `digitalhouses_plex_monitoring`

**Status:** Active — first `linux_agent` reference implementation.

Type:

```ini
type = linux_agent
```

Initial runtime model:

```text
Linux VM/LXC
    ↓
native Python agent
    ↓
systemd service
    ↓
configuration from *.conf
    ↓
publishing/monitoring integration
```

Canonical configuration path:

```text
/etc/digitalhouses_plex_monitoring/digitalhouses_plex_monitoring.conf
```

Installation and updates use the same idempotent:

```text
install.sh
```

The installer must preserve an existing `.conf`.

---

# Part VII — Release readiness

## 43. Common release readiness

A release is ready only when:

- `digitalhouses.app` exists and declares a supported type;
- common validation passes;
- the declared type contract passes;
- all tests pass together;
- application-specific regression checks pass;
- release documentation is current;
- changelog is current;
- no private site dependencies are embedded in reusable public code.

---

## 44. HAOS add-on release readiness

Additionally:

- `config.yaml` version is authoritative;
- Dockerfile version matches;
- CHANGELOG version matches;
- Python compile passes;
- `run.sh` syntax passes;
- translations parse;
- published architectures are correct.

Future:

- Docker build passes for every published architecture.

---

## 45. Linux agent release readiness

Additionally:

- `VERSION` is authoritative;
- CHANGELOG version matches;
- Python compile passes where applicable;
- unit tests pass;
- `install.sh` syntax passes;
- systemd validation passes;
- canonical `.conf` behavior is documented;
- canonical filesystem layout is respected;
- installer is idempotent;
- installer preserves existing configuration;
- Git-based installations expose release version, source ref, and exact commit identity.

---

# Part VIII — Migration plan

## 46. Phase 1 — Introduce application types

Add:

```text
digitalhouses_speedtest/digitalhouses.app
digitalhouses_db_monitoring/digitalhouses.app
```

with:

```ini
type = haos_addon
```

Introduce type-aware validation.

Do not infer type from existing files.

---

## 47. Phase 2 — Make current CI truthful

- common repository validation;
- HAOS type validation;
- Speedtest full CI;
- DB Monitoring full CI;
- fix DB Monitoring test isolation;
- synchronize HAOS version contracts.

---

## 48. Phase 3 — Extract app-specific validators

Move Speedtest-specific compatibility checks out of generic repository validation.

Create DB Monitoring regression checks.

---

## 49. Phase 4 — Introduce templates

Create and validate:

```text
templates/haos_addon/
templates/linux_agent/
```

---

## 50. Phase 5 — Introduce first Linux agent

Create:

```text
digitalhouses_plex_monitoring
```

from the `linux_agent` template.

Its first implementation becomes the reference validation case for the Linux-agent contract.

---

## 51. Phase 6 — Build validation

Add Docker build smoke-test matrix for HAOS add-ons.

Add Linux-agent installer/systemd validation appropriate for CI.

---

# Part IX — Final design rule

The DigitalHouses repository has three independent layers:

```text
Common Application Standard
        ↓
Application Type Contract
        ↓
Application-Specific Compatibility Contract
```

Therefore:

```text
digitalhouses_*
```

means:

> a DigitalHouses-managed application governed by the common standard.

It does **not** mean:

> a Home Assistant OS add-on.

Runtime model, mandatory files, installation method, configuration format, and CI checks are selected explicitly through:

```text
digitalhouses.app
```

This explicit type declaration is mandatory and stable.
