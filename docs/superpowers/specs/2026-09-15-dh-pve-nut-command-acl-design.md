# DH PVE NUT Command ACL Design

## Goal

Make UPS/NUT commissioning complete and self-consistent from first setup through normal operation, so `dh_pve_app` never reaches a state where it has valid NUT command credentials but the configured NUT user lacks the permissions required by App controls.

## Ownership model

`dh_primary_user` is the single local NUT control identity owned by the Proxmox host for this installation.

It serves two purposes:

- `upsmon` authenticates as `dh_primary_user` with role `primary`;
- `dh_pve_app` uses the same identity for authenticated `upscmd` calls.

The commissioned NUT user is intentionally administrative for the local UPS:

```ini
[dh_primary_user]
    password = <managed secret>
    upsmon primary
    instcmds = ALL
```

`instcmds = ALL` grants the NUT account access to the UPS instant-command inventory. It does **not** expose arbitrary UPS commands to Home Assistant. `dh_pve_app` remains the application security boundary: MQTT/Home Assistant may invoke only commands explicitly implemented and allowlisted by App code. Arbitrary `upscmd`, `load.*`, `shutdown.*`, FSD, and shell execution remain unavailable through MQTT/HA unless a future reviewed App feature explicitly adds them.

## Lifecycle

The lifecycle is deliberately split into installation and commissioning.

1. `install.sh` installs or upgrades `dh_pve_app`, creates/preserves the App config, installs the systemd service, and configures MQTT. A physical UPS is not required.
2. The UPS is attached to Proxmox and discovered/selected by the existing read-only scan path.
3. Explicit root-only `--ups-policy-commission` performs the complete UPS/NUT administrative transaction.
4. After successful commissioning, normal `dh_pve_app.service` operation remains read-only with respect to `/etc/nut`; it reads telemetry/configuration and may execute only App-implemented authenticated UPS commands.
5. App upgrades do not rewrite NUT configuration. Recommissioning is explicit and is required when the UPS/NUT ownership configuration must be rebuilt or migrated.

## Commissioning preconditions

Commissioning keeps the existing safety gates:

- effective UID is root;
- a UPS is selected and readable;
- UPS is on stable line power;
- no battery test is running;
- no active `/etc/killpower` flag exists;
- current host is the NUT `PRIMARY` owner;
- Proxmox guest shutdown budget can be calculated;
- the static DigitalHouses shutdown helper is trusted and executable.

The commissioning preflight is extended to cover the control identity and its effective configuration.

## Managed files and transaction boundary

The commissioning transaction owns all files required to make the local PRIMARY and App command path coherent:

- `/etc/nut/ups.conf`
- `/etc/nut/upsd.users`
- `/etc/nut/upsmon.conf`
- `/etc/nut/upssched.conf`
- `/etc/dh_pve_app/dh_pve_app.conf` for the managed `[ups]` command credentials
- `/var/lib/dh_pve_app/ups_policy_active.json`

The static helper remains installed under `/opt/digitalhouses/dh_pve_app/bin/` and is validated but not generated dynamically.

Every managed file is snapshotted before the first write. NUT files retain the existing `/etc/nut` owner/group convention and mode `0640`; the App config remains root-owned and mode `0600`; metadata remains mode `0600`. On any failure after mutation begins, all file snapshots and relevant NUT service state are restored.

## Credential source of truth

Commissioning owns the `dh_primary_user` secret.

Rules:

- If `[dh_primary_user]` already exists in `upsd.users` with a non-empty password, preserve that password.
- Otherwise generate a cryptographically secure random password during commissioning.
- The resulting password is written consistently to the `dh_primary_user` section in `upsd.users`, the `MONITOR` line in `upsmon.conf`, and `[ups].command_username` / `[ups].command_password` in `dh_pve_app.conf`.
- The username is always `dh_primary_user` for the locally commissioned PRIMARY/App command path.
- Secrets must never be included in MQTT state, logs, exception text, policy hashes, README examples, or commissioning result text.

This removes independent manual credential copies and makes the transaction the single authority for the local NUT control identity.

## Rendering rules

### `upsd.users`

Commissioning creates or replaces only the `[dh_primary_user]` section and preserves unrelated NUT users/sections.

The managed section is canonical:

```ini
[dh_primary_user]
    password = <secret>
    upsmon primary
    instcmds = ALL
```

Duplicate `dh_primary_user` sections are rejected rather than guessed around.

### `upsmon.conf`

The selected UPS `MONITOR` entry is normalized to use the commissioned credentials and `primary` role:

```text
MONITOR <ups-name>@127.0.0.1 1 dh_primary_user <secret> primary
```

Other existing shutdown-policy directives continue to be managed by the current renderer.

### App config

Commissioning updates the existing `[ups]` section without changing unrelated sections/settings. It ensures:

```ini
[ups]
enabled = true
name = <selected ups name>
command_username = dh_primary_user
command_password = <secret>
```

Existing host, port, polling and timeout values are preserved unless already controlled by the existing commissioning contract.

## Service application order

After all target files are written and content-verified:

1. restart the selected NUT driver as required by existing UPS delay handling;
2. restart/reload the NUT server so `upsd.users` takes effect;
3. verify the configured `dh_primary_user` can authenticate to the selected UPS command endpoint and that the UPS command inventory is readable;
4. wait for and verify the effective hardware restore delay as today;
5. restart or enable/start `nut-monitor.service` according to its pre-transaction state;
6. persist policy metadata only after the whole transaction has passed verification.

If a required service or verification step fails, rollback restores every managed file and prior monitor/server state as far as systemd permits.

## Preflight / readiness contract

Read-only `--ups-policy-preflight` must distinguish telemetry availability from command authorization readiness.

At minimum it reports checks equivalent to:

- UPS selected/reachable;
- NUT server available;
- `[dh_primary_user]` exists;
- `dh_primary_user` has `upsmon primary`;
- `dh_primary_user` has `instcmds = ALL`;
- `upsmon.conf` PRIMARY `MONITOR` uses `dh_primary_user`;
- App `[ups].command_username` is `dh_primary_user`;
- App and NUT credentials are internally consistent without exposing the password;
- shutdown policy is otherwise valid.

A missing/mismatched ACL must make commissioning/readiness non-ready, rather than allowing Home Assistant controls to appear operational merely because `command_username` and `command_password` are non-empty.

## Runtime contract

The long-running daemon remains unable to edit `/etc/nut`.

Runtime control behavior stays capability-driven and explicit in App code. `instcmds = ALL` is not interpreted as permission to surface every UPS command. Existing battery-test and beeper allowlists remain intact; dangerous or arbitrary command families stay unavailable to MQTT/Home Assistant.

A command failure such as `ERR ACCESS-DENIED` is still treated as a runtime error and never converted into optimistic HA state.

## Upgrade and migration behavior

Existing installations are not silently rewritten by `install.sh`.

For an already commissioned host, running explicit commissioning after this change migrates the local NUT control identity into the managed contract:

- preserve the existing `dh_primary_user` password when present;
- add/normalize `upsmon primary` and `instcmds = ALL`;
- synchronize `upsmon.conf` and App command credentials;
- preserve unrelated NUT users and unrelated App config;
- verify the effective command path before reporting success.

This directly fixes the production failure where battery-test permissions existed but newly added beeper commands returned `ERR ACCESS-DENIED`.

## Tests

Regression coverage must prove:

- `upsd.users` is part of `ManagedNutPaths` and every apply/rollback snapshot;
- renderer preserves unrelated users while canonicalizing only `dh_primary_user`;
- existing `dh_primary_user` password is preserved;
- missing user causes secure secret generation and synchronized writes;
- `upsmon.conf`, `upsd.users`, and App config receive one consistent identity;
- secrets do not leak through errors/results;
- NUT server restart/reload is included before command-path verification;
- failure after each mutation/service stage restores all managed files;
- preflight fails when `dh_primary_user` is absent, is not PRIMARY, lacks `instcmds = ALL`, or App credentials do not match;
- runtime service sandbox remains read-only for `/etc/nut`;
- existing App command allowlists still reject dangerous/arbitrary commands even though the NUT user has `instcmds = ALL`.

## Non-goals

- No Home Assistant control for commissioning or NUT file editing.
- No second NUT App user.
- No automatic NUT rewrite during ordinary App upgrade/startup.
- No destructive FSD test.
- No expansion of the MQTT command surface beyond the commands already explicitly implemented by `dh_pve_app`.
