# UPS / NUT shutdown setup for DigitalHouses PVE Agent

This guide explains how to prepare a Proxmox VE host, Network UPS Tools (NUT), and DigitalHouses PVE Agent for a predictable UPS-triggered shutdown.

The goal is not merely to make the readiness sensor green. The goal is to make every readiness condition understandable and verifiable before a real power failure occurs.

## Responsibility boundary

The shutdown authority stays on the Proxmox host:

```text
UPS -> NUT driver -> upsd -> upsmon PRIMARY -> Proxmox shutdown
                                      |
                                      +-> DigitalHouses PVE Agent -> MQTT -> Home Assistant
```

Home Assistant is not part of the safety path. The long-running `digitalhouses_pve_agent.service` observes NUT and PVE state but does not rewrite `/etc/nut`.

The helper scripts in `tools/ups/` are commissioning tools. Commands in this guide execute them directly from GitHub, so they do not depend on a local Agent installation:

- `nut-readiness-audit.sh` is read-only;
- `nut-install-packages.sh` installs NUT packages only;
- `nut-stage-primary-config.sh` generates configuration in a staging directory.

None of these scripts issues FSD, switches UPS output off, runs arbitrary `upscmd`, or performs a live shutdown test.

## What "ready" means

A normal local PRIMARY installation is ready when all of the following are true:

1. Linux can communicate with the UPS through the correct NUT driver.
2. `upsd` can publish the selected UPS.
3. The PVE host has a local `upsmon` MONITOR entry for that UPS with role `primary`.
4. `nut-monitor.service` is active.
5. `SHUTDOWNCMD` is a real host shutdown command, not the commissioning placeholder `/bin/true`.
6. The selected UPS configuration exposes a readable restore delay (`ondelay`) when the driver/device supports it.
7. If DigitalHouses PVE Agent is installed, it uses the same UPS name and PRIMARY credentials.
8. Proxmox guest lifecycle settings (`onboot`, `startup: order=...,down=...`) describe the intended shutdown order and timeouts.
9. If DigitalHouses PVE Agent is installed, its read-only preflight reports no remaining blocking conditions.

A warning in Home Assistant is therefore a request to inspect one of these conditions, not a request to change an Agent setting blindly.

## 1. Run the read-only audit first

On the Proxmox host:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/DigitalHouses/home-assistant-apps/main/digitalhouses_pve_agent/tools/ups/nut-readiness-audit.sh)
```

The audit does not modify NUT or PVE. It reports PVE/NUT package state, NUT mode, configured UPS names, service state, USB discovery when available, a password-safe subset of MONITOR configuration, and the Agent preflight.

The command above runs the read-only script directly from this GitHub repository. **DigitalHouses PVE Agent is not required.** If the Agent is installed, the audit also runs its preflight. If it is not installed, the host/NUT/UPS audit still runs normally and the Agent-specific preflight is simply skipped.

## 2. Install NUT packages

For a directly connected USB UPS:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/DigitalHouses/home-assistant-apps/main/digitalhouses_pve_agent/tools/ups/nut-install-packages.sh) --transport usb
```

For an SNMP/network UPS:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/DigitalHouses/home-assistant-apps/main/digitalhouses_pve_agent/tools/ups/nut-install-packages.sh) --transport snmp
```

Use `--no-update` only when package metadata has already been refreshed. The helper does not create `/etc/nut` configuration and does not itself invoke service start/restart commands. Debian package post-install scripts may still initialize units according to package policy, so check service state with the read-only audit after installation.

## 3. Identify the UPS and choose the driver

For USB, start with:

```bash
nut-scanner -U
```

For many USB HID devices the driver is `usbhid-ups` with `port = auto`, but do not assume this for an unknown model. Compare scanner output with the NUT Hardware Compatibility List and driver documentation. Prefer stable vendor/product/serial identification over volatile USB bus/device numbers.

For an SNMP/network UPS, the usual driver family is `snmp-ups`, but MIB, SNMP version, credentials, permissions, and firmware behavior are device-specific.

For a real field example, see [CyberPower RMCARD205 network UPS field case](../hardware/cyberpower-rmcard205/README.md). It describes one installation and is not a universal default.

Official NUT references:

- <https://networkupstools.org/documentation.html>
- <https://networkupstools.org/stable-hcl.html>
- <https://networkupstools.org/docs/man/nut-scanner.html>
- <https://networkupstools.org/docs/man/ups.conf.html>
- <https://networkupstools.org/docs/man/upsmon.conf.html>

## 4. Generate a safe PRIMARY staging configuration

The staging helper never writes to `/etc/nut`. Its output directory must resolve below `/root` and must be empty, which keeps generated credentials and configuration away from live NUT files.

Example:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/DigitalHouses/home-assistant-apps/main/digitalhouses_pve_agent/tools/ups/nut-stage-primary-config.sh) \
  --ups-name ups \
  --driver usbhid-ups \
  --port auto
```

If the selected driver/device supports a known restore delay, add it explicitly:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/DigitalHouses/home-assistant-apps/main/digitalhouses_pve_agent/tools/ups/nut-stage-primary-config.sh) \
  --ups-name ups \
  --driver usbhid-ups \
  --port auto \
  --ondelay 120
```

The helper generates a cryptographically random local `dh_primary_user` service credential. The secret is written only to the private staging files and is not printed to the terminal. It creates a private staging directory containing `nut.conf`, `ups.conf`, `upsd.conf`, `upsd.users`, `upsmon.conf`, and `digitalhouses_pve_agent-ups.ini`.

The generated `upsmon.conf` intentionally contains:

```text
SHUTDOWNCMD "/bin/true"
```

This is a commissioning safety state. NUT can be validated without allowing an unexpected UPS event to shut down the host. Home Assistant should continue to show automatic shutdown as not ready until final activation.

Driver-specific options are deliberately not guessed.

## 5. Review and apply the staged NUT files

Do not copy generated files blindly. Review them first. Do not print `upsd.users`, `upsmon.conf`, or the Agent snippet into shared logs because they contain the commissioning password.

Before replacing an existing NUT setup, back it up:

```bash
BACKUP="/root/nut-backup-$(date +%Y%m%d-%H%M%S)"
mkdir -m 0700 "$BACKUP"
cp -a /etc/nut/. "$BACKUP"/
```

For a standard Debian/Proxmox installation, review ownership on existing files and install the reviewed staged files with restricted permissions. A common layout uses `root:nut` and mode `0640`, but preserve the local package/installation ownership contract rather than forcing an unknown one.

At this commissioning stage, keep `nut-monitor.service` stopped or inactive. Bring up only the driver/server path needed to validate UPS communication.

Exact service unit names can differ by NUT packaging and driver model. Inspect them first:

```bash
systemctl list-unit-files 'nut*'
systemctl status nut-server.service --no-pager
```

Then verify that `upsd` can publish the UPS:

```bash
upsc -l 127.0.0.1
upsc ups@127.0.0.1
```

Replace `ups` with the selected UPS name.

## 6. Configure DigitalHouses PVE Agent (optional)

This section is only for hosts where DigitalHouses PVE Agent is installed. If the Agent is not installed, skip this section; NUT and Proxmox shutdown configuration work independently.

Merge the values from `digitalhouses_pve_agent-ups.ini` into:

```text
/etc/digitalhouses_pve_agent/digitalhouses_pve_agent.conf
```

The important relationship is:

```text
upsd.users [dh_primary_user] password
        =
upsmon.conf MONITOR password
        =
DigitalHouses PVE Agent [ups] command_password
```

The username is `dh_primary_user`.

Restart only the Agent after editing its own configuration:

```bash
systemctl restart digitalhouses_pve_agent.service
systemctl status digitalhouses_pve_agent.service --no-pager
```

Then run the read-only preflight:

```bash
PYTHONPATH=/opt/digitalhouses/digitalhouses_pve_agent \
/opt/digitalhouses/digitalhouses_pve_agent/.venv/bin/python -m app.main \
  --config /etc/digitalhouses_pve_agent/digitalhouses_pve_agent.conf \
  --state-dir /var/lib/digitalhouses_pve_agent \
  --ups-policy-preflight
```

During commissioning it is expected that shutdown checks remain blocked while `SHUTDOWNCMD` is `/bin/true` and `nut-monitor` is inactive.

## 7. Configure the Proxmox guest lifecycle

The Agent observes guest lifecycle settings; it does not change them.

For every production VM/LXC, decide whether it starts automatically (`onboot=1`), its startup/shutdown group (`startup: order=<n>`), and its shutdown timeout (`startup: ...,down=<seconds>`).

Proxmox shuts guests down in reverse startup order. Guests with the same order form the same shutdown group. Use a timeout comfortably above measured normal shutdown duration; do not copy values from another site just to make readiness green.

After changing lifecycle settings, refresh the Agent and confirm that the shutdown chain and budget in Home Assistant match the intended topology.

## 8. Final production activation

Do this only after the driver is stable, `upsc` reads the expected UPS consistently, PRIMARY credentials match, guest lifecycle is reviewed, preflight has no unexplained failures, and console access plus a maintenance window are available.

The safe staging file uses:

```text
SHUTDOWNCMD "/bin/true"
```

For the normal Proxmox/NUT PRIMARY shutdown path used by this project, the reviewed production value is:

```text
SHUTDOWNCMD "/sbin/shutdown -h now"
```

Apply that change manually to the reviewed `upsmon.conf`, then enable/start the local NUT monitor using the service name provided by the installed NUT package.

This step is intentionally not automated by the commissioning toolkit because it changes the host from monitoring-only to an active emergency shutdown path.

If DigitalHouses PVE Agent is installed, run its preflight again. Otherwise continue directly to validation.

## 9. Validate without a live shutdown

Repeat the read-only audit:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/DigitalHouses/home-assistant-apps/main/digitalhouses_pve_agent/tools/ups/nut-readiness-audit.sh)
```

Confirm the selected UPS is readable, NUT services have expected state, and MONITOR role is PRIMARY. If DigitalHouses PVE Agent is installed, also confirm its preflight is ready and the Home Assistant shutdown chain/budget match PVE configuration.

A green readiness result proves internal configuration consistency. It is not proof that a physical power-loss cycle was tested.

## 10. Configure the Agent software trigger policy

The NUT PRIMARY path is the shutdown authority. DigitalHouses PVE Agent adds a
software trigger policy on top of that path; it does not replace native NUT Low
Battery handling.

The software policy is:

```text
Trigger A: on battery AND battery.charge <= configured charge threshold
OR
Trigger B: on battery AND battery.runtime <= shutdown budget + runtime reserve
OR
native NUT Low Battery emergency path
```

In Home Assistant, use the PVE Agent UPS policy controls:

- **Battery charge shutdown threshold**: 10..30 %, step 5;
- **Runtime reserve**: 60..900 seconds, step 60;
- **Apply trigger policy**: commits the reviewed draft.

Changing a number edits only the draft. Pressing **Apply** is required to commit
the policy. The current default runtime reserve is 180 seconds, but choose values
for the actual UPS load, battery condition, shutdown budget, and operational
margin rather than copying another site.

The Agent's Apply workflow does not turn Home Assistant into the shutdown
authority. When a software threshold is reached, the Agent can call only its
fixed local FSD helper; NUT/Proxmox still owns the actual shutdown path.

After Apply, confirm the committed policy entity, refresh the Agent, and run the
read-only audit again.

## 11. Controlled live shutdown test

A real FSD/power-loss test is an operational maintenance procedure, not an installation command. The helper scripts in this repository do not perform it.

Before a controlled live test, take required backups, ensure console access, confirm guest shutdown timing, confirm UPS runtime margin, follow the UPS vendor restore procedure, and have an explicit rollback/recovery plan.

Only after that controlled test should historical measured shutdown duration be used to judge real margin below the configured worst-case budget.

## Readiness messages

The Agent keeps machine-readable reason codes for diagnostics. The Home Assistant card translates them into user-facing guidance.

| Reason | Meaning | What to check |
| --- | --- | --- |
| `shutdown_policy_unavailable` | NUT shutdown policy could not be read | NUT files, permissions, selected UPS and Agent preflight |
| `nut_unavailable` | Selected UPS cannot currently be read through NUT | Driver, cable/network path, `upsd`, UPS name |
| `shutdown_policy_not_enabled` | Observed NUT shutdown path is not active | Complete commissioning; do not bypass preflight |
| `nut_role_not_primary` | This PVE host is not configured as NUT PRIMARY | Local MONITOR entry and `dh_primary_user` |
| `nut_monitor_not_active` | `nut-monitor` is not active | Final production activation and service state |
| `shutdown_disabled` | NUT cannot execute the real host shutdown command | Review `SHUTDOWNCMD`; commissioning `/bin/true` is intentionally disabled |
| `power_restore_delay_unreadable` | Agent cannot read the selected UPS restore delay | Driver support/configuration for `ondelay` |
| `shutdown_budget_unavailable` | PVE shutdown budget cannot be calculated | Guest lifecycle configuration and Agent diagnostics |
| `previous_host_shutdown_unclean` | A previous UPS-triggered host shutdown was confirmed unclean | Shutdown history and system journal |
| `previous_host_shutdown_unknown` | Previous UPS-triggered shutdown lacks clean/unclean evidence | Shutdown history and journal retention |
| `vm:<id>:near_timeout` / `lxc:<id>:near_timeout` | Measured guest shutdown was close to its current timeout | Increase timeout or investigate slow shutdown |
| `vm:<id>:timeout` / `lxc:<id>:timeout` | Guest reached its shutdown timeout | Guest shutdown behavior and configured `down=` |
| `vm:<id>:forced` / `lxc:<id>:forced` | Guest required forced termination | Guest shutdown behavior before relying on UPS automation |

## Safety rules

- Do not set `ignorelb` merely to silence a warning. Native UPS/NUT Low Battery behavior is an emergency safety path.
- Do not expose arbitrary NUT commands through Home Assistant.
- Do not put the PRIMARY password in shell history, tickets, screenshots, or shared logs.
- Do not use a live shutdown event as the first validation step.
- Do not change guest `down=` only to make a warning disappear; investigate actual shutdown behavior first.
