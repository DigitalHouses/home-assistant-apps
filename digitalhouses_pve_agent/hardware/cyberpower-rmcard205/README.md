# CyberPower PR3000ELCDSL / RMCARD205 — network UPS (NUT + Proxmox VE)

Field-tested setup: 2026-10-03, Proxmox VE 8.x / Debian 12, CyberPower PR3000ELCDSL with RMCARD205.
**Scope: host NUT and UPS management card only. The DigitalHouses PVE Agent is unchanged.**

## Architecture

```text
CyberPower PR3000ELCDSL / RMCARD205 (SNMP)
             |
          Ethernet
             |
Proxmox: NUT snmp-ups -> upsd: ups@127.0.0.1
             |                 |
             |                 +-- NUT SECONDARY clients
             +-- PVE Agent -> MQTT Discovery -> Home Assistant
```

PVE/NUT is the PRIMARY shutdown authority. Preserve the logical name `ups`, NUT users, `upsmon` and PVE Agent settings when migrating from USB (`usbhid-ups`) to SNMP (`snmp-ups`). HA is not the safety/shutdown decision-maker. The router and UPS management network may have UPS power, but PVE's own networking service can still stop before the OS is halted.

This is a **manual site commissioning case**, not an automatic Agent installation/upgrade feature.

## RMCARD205 configuration

In the management web UI, open **System -> Network Service -> SNMPv1 Service**.

- Enable SNMPv1.
- Configure an SNMP **Read/Write** community for the NUT host. SNMP shutdown requires SET, not just GET.
- Use the exact same community in `/etc/nut/ups.conf`. SNMPv1 is unencrypted; site owners choose the network restrictions and secret appropriate to their environment.

At this site `public` was Read Only and `private` was Read/Write. These are **observed example roles, not recommended credentials**. A read-only `GET` with `public` succeeded, while `SET` timed out. A repeat using Read/Write succeeded.

To validate Read/Write without changing power, retrieve the standard system-contact OID `.1.3.6.1.2.1.1.4.0` and write **exactly its existing string** back as SNMP type `s`. A returned string (here `Administrator`) confirms a harmless SET accepted. It does **not** prove `shutdown.return` works. Never use load-off/shutdown commands as a connection test.

SNMPv3 (`authPriv`, SHA/AES) also returned `OL` with NUT 2.8.5 during commissioning, but the earlier connection subsequently showed `Data stale`. SNMPv3 power-command permission was **not** validated here. The final working deployment uses SNMPv1.

Do not commit real community strings, passwords, serial numbers, or local configuration backups to this public repository.

## NUT requirements and setup

In this installation Debian 12's NUT **2.8.0** (`cyberpower MIB 0.51`) could read some SNMP fields but did not reliably expose `ups.status`. Updating via upstream's prepared official packages to **NUT 2.8.5** (`cyberpower MIB 0.56`) fixed the observed missing `OL`. This is a field observation, not a statement about every card or older NUT build.

Example `/etc/nut/ups.conf` (substitute the card address and the community; **one** `[ups]` section):

```ini
[ups]
    driver = snmp-ups
    port = <UPS_CARD_IP>
    mibs = cyberpower
    snmp_version = v1
    community = "<READ_WRITE_COMMUNITY>"
    desc = "CyberPower PR3000ELCDSL"
```

Keep access restricted (observed `root:nut`, mode `0640`). Preserve the preceding known-good configuration, USB connection fallback and NUT user configuration; do not rewrite `upsmon`, `upsd` or PVE Agent settings. In the original site the backups were named `/etc/nut/ups.conf.usb-before-285-snmp` and `/etc/nut/ups.conf.v3-before-v1`. A driver restart is needed to activate changed connection settings, under stable line power and without an active FSD flag.

**Non-destructive verification**:

```bash
upsc ups@127.0.0.1 driver.name
upsc ups@127.0.0.1 driver.parameter.snmp_version
upsc ups@127.0.0.1 driver.version.data
upsc ups@127.0.0.1 ups.status
upsc ups@127.0.0.1 battery.charge
upsc ups@127.0.0.1 battery.runtime
upsc ups@127.0.0.1 input.voltage
systemctl is-active nut-driver@ups.service nut-server.service nut-monitor.service
```

Observed acceptance: `snmp-ups`, `v1`, NUT 2.8.5, CyberPower MIB 0.56 and `OL`; all three services `active`; six `OL` polls spaced 10 seconds apart, without `Data stale`; HA successfully displayed UPS status and input voltage. Sample readings: 100% charge, 8% load, 238.2 V, 4,500 s runtime. These are measured values, **not** alarm or shutdown thresholds.

## SNMP-specific shutdown ordering

The stock final systemd shutdown hook `/lib/systemd/system-shutdown/nutshutdown` checks `upsmon -K` and calls `upsdrvctl shutdown`. This is suitable for a locally attached USB UPS. For SNMP, the late hook may run **after the networking interface is removed**. Upstream NUT's `snmp-ups.c` explicitly warns about this limitation.

This site installed exactly **one systemd drop-in** at
`/etc/systemd/system/nut-driver@ups.service.d/20-fsd-network-shutdown.conf`:

```ini
[Unit]
After=networking.service
Before=pve-guests.service

[Service]
ExecStopPost=/bin/sh -c 'if systemctl is-system-running 2>/dev/null | grep -qx stopping && /sbin/upsmon -K >/dev/null 2>&1; then echo "NUT FSD: sending UPS shutdown"; if /usr/bin/timeout 45 /sbin/upsdrvctl shutdown ups; then echo "NUT FSD: driver returned success"; rm -f /etc/killpower; else echo "NUT FSD: failed, late fallback retained"; fi; fi'
```

Systemd stop order is the inverse of start ordering:

1. `pve-guests.service` stops guests using normal Proxmox logic.
2. NUT stops its driver, with `networking.service` still alive.
3. `ExecStopPost` checks **both** systemd's `stopping` state and NUT's actual FSD powerdown flag (`upsmon -K`). With both present, it runs the standard `upsdrvctl shutdown ups` while the network is available.
4. On a successful exit, the NUT flag is removed to avoid duplicate late-hook commands. On failure, the flag remains for the standard fallback (which may not have network access).
5. PVE continues to shut down; UPS handles its own delay/restore behavior.

**Do not run `upsdrvctl shutdown`, `upsmon -c fsd`, `upscmd shutdown.return`, `load.off`, or any real output-off test during routine commissioning.** This power-off path has consequences for PVE, guests and storage.

The observed card values were `ups.delay.shutdown=180` seconds and `ups.delay.start=300` seconds. `driver.flag.allow_killpower=0` is a normal guard for direct `driver.killpower`, distinct from the standard `upsdrvctl shutdown` path. The displayed `shutdown.return` command does not independently prove hardware execution.

### Verified versus unverified

**Verified without a shutdown**: override accepted by `systemd-analyze --man=no verify nut-driver@ups.service`; `systemctl daemon-reload`; NUT services remain `active` and UPS `OL`; live unit has `Before=pve-guests.service`, `After=networking.service` and the intended `ExecStopPost`. `upsmon -K` confirmed **no FSD** during normal operation.

**Not yet verified**: an actual FSD path, successful physical execution of `shutdown.return`, UPS output cycling, recovery on return of mains, and whether the remaining 180 seconds is sufficient for the actual host tail. A maintenance-window test requires separate approval and shutdown budget validation. The override is not a guarantee of UPS cut-off without those tests.

### Battery diagnostic result codes

For the standard manual NUT test (`test.battery.start`), the CyberPower
SNMP MIB exposes the following *observed/defined* `ups.test.result` strings:

| NUT value | Meaning for the history |
| --- | --- |
| `TestInProgress` | Running, not yet finished |
| `Ok` | Passed |
| `Failed` | Failed |
| `InvalidTest` | Failed (invalid diagnostic request) |

Version 0.5.52 of the PVE Agent did not recognize the final `Ok` value,
so an already-running history record could remain indefinitely open.
The generic NUT result parser is corrected in 0.5.53 without any
model-, vendor- or transport-specific logic.

Read only: `upsc ups@127.0.0.1 ups.test.result`,
`upsc ups@127.0.0.1 ups.test.date`. Never presume a test
finished just because a short duration passed; check the actual NUT
result and distinguish it from a pre-test value. The completed time
in PVE Agent history is the **first observed** completion time, not a
hardware-provided exact timestamp.

### Read-only audit

```bash
systemctl show nut-driver@ups.service -p Before -p After -p ExecStopPost --no-pager
systemctl show nut-driver@ups.service nut-server.service nut-monitor.service -p Id -p ActiveState -p Result --no-pager
systemctl is-system-running
/sbin/upsmon -K
upsc ups@127.0.0.1 ups.status
```

A missing FSD flag is **expected** during normal operation. If `systemd-analyze verify` emits only `man upsdrvsvcctl(8)` lookup failures on this Debian host, use `systemd-analyze --man=no verify` to check unit correctness without manual-page diagnostics.

### Rollback

- To roll back shutdown ordering only, delete **only** the above drop-in and run `systemctl daemon-reload`; retain other drop-ins.
- To roll back transport, restore a matching known-good USB/SNMP configuration backup and restart the NUT driver under stable utility power, with no active FSD. Keep the identical `ups` name and recheck `upsc` values.
- An unrelated systemd `degraded` state was caused here by `zfs-import-scan.service` attempting to import TrueNAS-owned `boot-pool`/`sky_pool` with a “previously in use from another system” protection response; `zpool list` showed **no** PVE-imported pools, while NUT services were all healthy. Do not force-import guest-owned TrueNAS pools or modify NUT merely to clear that warning.

## Upstream references

- [NUT 2.8.5 SNMP driver](https://github.com/networkupstools/nut/blob/v2.8.5/drivers/snmp-ups.c) and [CyberPower MIB](https://github.com/networkupstools/nut/blob/v2.8.5/drivers/cyberpower-mib.c)
- NUT `upsdrvctl(8)`, `upsmon(8)`, `ups.conf(5)` and upstream systemd shutdown integration.
