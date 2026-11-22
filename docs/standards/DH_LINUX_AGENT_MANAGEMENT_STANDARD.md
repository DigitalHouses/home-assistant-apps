# DigitalHouses Linux Agent Management Standard

**Status: MANDATORY**  
**Applies to:** all DigitalHouses Linux/systemd agents, including PVE, PBS and Plex Agents.
**Compliance:** documentation is not implementation. An agent release must satisfy and test this contract before claiming compliance.

This is the normative shared standard for CLI commands, native configuration, the root quick reference and Linux host identity in Home Assistant. Product-specific parameters remain defined in each agent's README. Do not introduce a second config database, management daemon or API.

## 1. CLI

Install the product's executable in `/usr/local/bin/`:

| Product | Absolute CLI path | Root quick reference | Native config |
| --- | --- | --- | --- |
| Plex Agent | `/usr/local/bin/dh-plex-agent` | `/root/dh-plex-agent.txt` | `/etc/digitalhouses_plex_agent/digitalhouses_plex_agent.conf` |
| PVE Agent | `/usr/local/bin/dh-pve-agent` | `/root/dh-pve-agent.txt` | `/etc/digitalhouses_pve_agent/digitalhouses_pve_agent.conf` |

Mandatory subcommands (using the product's full executable path):

- `status`: show installed version and commit, systemd service state/uptime, actual Linux hostname and primary IPv4 (or unknown), configured MQTT host/port, MQTT connected/disconnected state, last successful connection, reconnect interval, publication state, last successful publication/ACK (where known), relevant errors and product-specific status (for example Plex API). Work even when MQTT is offline or service is stopped; clearly distinguish live runtime status from a stale snapshot. Never equate local MQTT queue acceptance with broker acknowledgement.
- `restart`: restart **only** the existing agent systemd unit, not Plex/PVE/VMs or other services.
- `set key=value [key=value ...]`: native, idempotent config management. Support one or multiple key/value pairs.
- `help`: list all CLI commands and every supported configurable key, validation constraints and the full reference URL.

## 1.1. PVE Agent is the operational CLI reference (mandatory)

**Copy the existing behavior, not an approximate imitation.** For the common
administrative interface, the **current maintained PVE Agent on `main`** is
the authoritative reference. Developers must inspect these sources **before**
designing or modifying the CLI of another Linux Agent:

- [PVE CLI implementation](../../digitalhouses_pve_agent/app/cli.py)
- [PVE CLI executable](../../digitalhouses_pve_agent/bin/dh-pve-agent)
- [PVE README and command reference](../../digitalhouses_pve_agent/README.md)
- [PVE CLI tests](../../digitalhouses_pve_agent/tests/)

Port the PVE presentation and behavior to PBS, Plex and future Linux Agents,
replacing only the product name, command/service/config paths and real
product-specific facts. Common text is shared **verbatim** wherever the action
and meaning are the same. Do not redesign labels, output layout, command
semantics, success/error messages or update formatting simply because another
presentation seems equivalent.

| Common action | Canonical PVE-facing behavior to reproduce |
| --- | --- |
| `status` | Compact, human-readable summary: `DigitalHouses <Product> Agent <installed-version> | commit <commit>` where verified; uppercase section headers; indented, aligned `Key: value` fields; stable order of applicable common sections such as `SYSTEM` and `MQTT`, followed by the relevant product monitoring blocks; explicitly distinguish LIVE from STALE/UNAVAILABLE. Read existing runtime state rather than triggering expensive probes. |
| `update` | Emit `UP_TO_DATE <installed-version>` if current; otherwise **before** installation emit `UPDATING <installed-version> -> <target-version>` and **only after actual version verification** emit `UPDATED <installed-version>`. Use a version, not the Git tag, as the final result. Preserve stdout flushing and nonzero failure behavior. |
| `restart` | Show `Restarted <product-systemd-unit>` only after a successful agent-only restart. Refuse to misrepresent an inactive agent as restarted. |
| `set` | Print exactly `CHANGED` or `UNCHANGED` with PVE-equivalent atomicity, safety, secret handling and conditional restart. |
| `auto-update on/off/status` | Report `CHANGED ON/OFF`, `UNCHANGED ON/OFF` or `ON/OFF` with the same meanings and persistence rules. |
| `help` | Match the PVE usage-line structure, absolute binary paths, command explanations, full native config key reference, constraints, protected secret input and documentation link; list genuine product extensions separately. |
| Errors | Prefix user-facing failures with `ERROR:`, use a nonzero exit status, avoid Python exception class names/tracebacks and secret-bearing raw inputs; align the wording of equivalent failure scenarios with PVE. |

**Product-specific exceptions are narrow.** PBS replaces PVE's hardware/UPS
sections with real datastore, snapshot, task, sync and capacity information;
Plex replaces them with real media/server facts. Domain-specific CLI commands
(for example PBS `check-update` or `telemetry-delete`) may be added without
changing common commands. Safety gates or runtime distinctions needed by the
product (such as UPS protection on PVE) remain product-owned. Never copy a
hardware probe, privileged action, unsafe assumption, unavailable datum or
secret merely for visual parity.

No new shared runtime library, CLI framework, daemon, configuration store or
product coupling is required. Reuse the proven implementation pattern locally;
each agent continues working independently. Preserve stable public CLI paths,
systemd units and Home Assistant MQTT identities.

**PVE is a moving, reviewed reference:** on every applicable CLI/HA-UI change,
reopen the current source on `main` instead of relying on a remembered
example or an old screenshot. If an existing PVE presentation contradicts
the repository's explicit safety/state contract, fix/resolve that conflict
in the reference and standard before propagating it; do not copy a defect.

## 2. Configuration

The existing INI configuration file remains the **single source of truth**. Direct editing and `set` are equally supported, including for Ansible. Every user-configurable native INI parameter must be manageable with `set`; short aliases are permitted and must map to the same actual INI field. E.g. `mqtt_ip` (or `mqtt_host` for a DNS name) maps to `[mqtt] host`. Document the complete mapping in GitHub.

`set` must validate **all** supplied values and cross-field constraints first, reject an invalid batch without partial writes, and atomically update only intended keys in the existing config while preserving other values, comments, owner and permissions. It must be safe to repeat: print `UNCHANGED` and perform no restart when values are already effective. For real changes, print `CHANGED` and restart the existing systemd agent **once if running**, but do **not** start an inactive agent. On failure print `ERROR`, return a nonzero exit status and do not report success. Configuration operations must not depend on MQTT or a monitored API being available.

Secrets: don't accept password values exposed in process arguments or shell history; provide hidden interactive entry and a safe non-argument automation mechanism (for example stdin). Never print passwords in `status`/`help` or logs. Ansible secret operations must use `no_log: true`.

The installer must support fully unattended provisioning using the already native configuration or installing CLI before configuration and activation; an interactive MQTT prompt must not be the only first-install path. Do not create a third installer-specific settings contract.

## 3. Root quick-reference TXT

The installer **must create/update** the product's `/root/dh-*-agent.txt` on each install or update. Keep it short and copy/paste friendly. **All agent commands have absolute executable paths.** Include `status`, `restart`, `help`, a native Linux `cat` command for the actual config, a few everyday `set` examples (MQTT host, port, log level), one multiple-key example and a GitHub link to the complete product configuration/CLI documentation. Do not list every key, include live credentials or create a large login banner. The `cat` command is native Linux; no CLI `cat` subcommand is required. Warn that the config may contain secrets.

Example for Plex (example IP is not installation configuration):

```text
DIGITALHOUSES PLEX AGENT
/usr/local/bin/dh-plex-agent status
/usr/local/bin/dh-plex-agent restart
cat /etc/digitalhouses_plex_agent/digitalhouses_plex_agent.conf
/usr/local/bin/dh-plex-agent set mqtt_ip=192.168.11.242
/usr/local/bin/dh-plex-agent set mqtt_port=1883
/usr/local/bin/dh-plex-agent set log_level=info
/usr/local/bin/dh-plex-agent set mqtt_ip=192.168.11.242 mqtt_port=1883
/usr/local/bin/dh-plex-agent help
Full reference: https://github.com/DigitalHouses/home-assistant-apps/tree/main/digitalhouses_plex_agent
```

## 4. Host identity in MQTT Discovery

Every agent must expose the actual **Linux machine hosting that agent** as two diagnostic sensors in its **existing MQTT Discovery device**:

- Plex: `sensor.dh_plex_agent_hostname`, `sensor.dh_plex_agent_ip`.
- PVE: `sensor.dh_pve_agent_hostname`, `sensor.dh_pve_agent_ip`.
- Future agents: their established entity prefix plus `_hostname` and `_ip`.

Hostname comes from Linux, not the UI device name. IP is the Linux machine's primary applicable IPv4, preferably the local source address of the route to the MQTT broker. In a VM it must be the **VM IP**, not Proxmox's or the broker's address. If unavailable/ambiguous, report unknown/unavailable rather than guess. Refresh at startup, after MQTT reconnect and upon detected network-address change. Add the same values to local CLI `status`. Keep stable existing MQTT topics, HA device identifiers and unique IDs; do not create a second device or rename existing entities. These diagnostic values should not be recorded in Recorder by default.

## 5. Mandatory release acceptance

Before marking an agent compliant, test and document:

1. `status`, `restart`, `help` with MQTT online/offline and service running/stopped; `status` does not misrepresent stale state.
2. Every native configurable key is supported by `set`; single/batch changes, input validation, atomic rollback on invalid input, idempotence, secret handling, exactly one restart for changed/running service, none for stopped/unchanged service.
3. Direct native configuration edits and unattended Ansible bootstrap; settings survive service/host restarts.
4. Short installed `/root` TXT with fully qualified commands and correct GitHub link.
5. Correct host Linux hostname/IP diagnostic sensors, no new HA device identity, and accurate updates after IP changes and MQTT reconnect.
6. PVE-parity CLI **golden-output tests** for the applicable `status`,
   `update` (up-to-date, new version, completed, failed/rollback),
   `restart`, `set`, `auto-update`, `help` and `ERROR:` paths. Compare
   the emitted section structure, field alignment, labels, message tokens,
   version pair and exit status to the current PVE reference under equivalent
   fixture states. Replace only product names/paths and real domain fields;
   explicitly document genuine exceptions.
7. No misleading live/stale values, invented installed versions, false
   success after a worker exits without installing, changed semantics,
   or additional dependencies solely to imitate a CLI layout.

**Adoption is per product.** This standard establishes the required target;
its publication does not by itself mean PBS/Plex CLI output is already
equivalent to PVE, and does not silently fail unchanged products in CI.
Add product-specific tests and complete the actual port in each product's
focused implementation and release.

**Separate policy:** an agent's MQTT failure mode (`MQTT_PAUSED` etc.) is product-specific and is **not** imposed on all agents by this management standard.
