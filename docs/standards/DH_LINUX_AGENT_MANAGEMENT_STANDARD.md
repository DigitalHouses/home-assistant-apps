# DigitalHouses Linux Agent Management Standard

**Status: MANDATORY**  
**Applies to:** all DigitalHouses Linux/systemd agents, initially `digitalhouses_plex_agent` and `digitalhouses_pve_agent`.  
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

**Separate policy:** an agent's MQTT failure mode (`MQTT_PAUSED` etc.) is product-specific and is **not** imposed on all agents by this management standard.
