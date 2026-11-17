# Proxmox VE 8/9 and GMKtec NucBox K15 — acceptance checklist

Scope: **digitalhouses_pve_agent only**. No changes to Ansible, DH Sync,
Plex Agent, HAOS or dashboard definitions.

## Compatibility policy

One release/installer for Proxmox VE 8.x and 9.x. Prefer Linux sysfs
capabilities over PVE-major conditionals. Source-level unit tests on Python
3.13 and synthetic PVE 9 records are **not** equivalent to passing a
live Proxmox VE 9 host acceptance test. The shipped PVE RRD index contract
was validated previously on 8.4; recheck the actual 9.2
`/etc/pve/.rrd`, `.vmlist`, `.version` schemas before marking 9.x fully
verified. Existing PVE 8 fixtures must continue passing.

## Confirmed K15 facts from the hardware lab (2026-11-17)

- Exact DMI `product_name=NucBox_K15`, board GMKtec V1.1.
- Proxmox VE 9.2, kernel 7.0.14-29-pve.
- Kernel `ec_sys` debugfs interface is available as
  `/sys/kernel/debug/ec/ec0/io`; `write_support=N`.
- RPM source is two big-endian 16-bit channels starting at EC offset 0x35:
  0x35–0x36 CPU FAN (confirmed by load response, ~1280 to ~2070 RPM),
  0x37–0x38 FAN2 (~1703 RPM, probable SYS FAN but not independently proven).
- Linux `hwmon` did not export these K15 fan inputs.
- The implementation never writes EC, enables PWM, changes fan speed,
  guesses `max_rpm`, scans arbitrary EC registers or runs a new daemon.

## Implementation

- `app/collectors/cooling.py` selects standard hwmon/IPMI first.
  Only an exact K15 DMI match with **no motherboard/BMC fan channel**
  activates `app/fan_hardware_gmktec_k15.py`.
- The agent reads two 4-byte EC samples in the already existing
  fan schedule (10-second FAST cycle), rejecting torn/out-of-range data.
  A read failure yields `rpm=None` / `available=False`, not 0 RPM.
  Existing FanPresence confirmation and entity IDs remain unchanged.
- The installer loads `ec_sys` and creates
  `/etc/modules-load.d/digitalhouses-pve-k15-ec.conf` only on K15,
  only when `write_support=N`. Uninstall removes only this owned entry;
  it does not unload the kernel module.
- This source is deliberately never eligible for PWM calibration.

## Live lab acceptance (requires K15 host access)

1. Run the normal released installer/upgrade on K15 PVE 9.2.
2. Confirm `cat /sys/class/dmi/id/product_name` equals
   `NucBox_K15`, and
   `cat /sys/module/ec_sys/parameters/write_support` equals `N`.
3. Check `dh-pve-agent status`: CPU FAN and FAN2 both have live RPM
   and current readings are not stale.
4. Check MQTT Discovery/HA: both RPM sensors belong to the existing
   DH PVE Agent device; no duplicate or renamed old sensors.
5. Under normal CPU load, CPU FAN increases from idle RPM while
   the BIOS remains in charge. Do not issue PWM/EC write commands.
6. Reboot the K15 and repeat 2–4 **without** a manual `modprobe`.
7. If EC is missing or returns invalid data, the service and other
   sensors keep working. Fan RPM becomes unavailable, not 0.
8. Confirm PVE node, VM/LXC, storage, disk/SMART, PCI/GPU, NUT/UPS,
   auto-update and CLI observations still work on 9.2.
9. Repeat the standard regression checks on a PVE 8.4 host. No model
   other than K15 should gain EC reads or `ec_sys` autoload entries.

Keep credentials, MQTT secrets, machine IDs and proprietary metadata out
of any shared test logs.
