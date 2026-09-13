# DH PVE App

`dh_pve_app` is the DigitalHouses native Linux agent for Proxmox VE. It collects host, CPU, memory, storage, physical-disk/SMART, GPU/transcoding, fan, VM/LXC and passthrough topology data and publishes normalized Home Assistant entities through MQTT Discovery. The same process can also monitor a locally connected UPS through Network UPS Tools (NUT).

Version `0.2.0-alpha` is the current UPS commissioning build. Proxmox/NUT owns the UPS and all emergency shutdown decisions; Home Assistant is an observability and battery-test UI, not a shutdown-policy authority.

## Public identity

- Home Assistant MQTT device: `DH PVE`
- Optional UPS MQTT device: `DH PVE UPS`
- MQTT base namespace: `DigitalHouses/Global/dh_pve_app/<instance>`
- PVE entity prefix: `dh_pve_`
- UPS entity prefix: `dh_pve_ups_`
- Service: `dh_pve_app.service`
- Install directory: `/opt/digitalhouses/dh_pve_app/`
- Config: `/etc/dh_pve_app/dh_pve_app.conf`
- Persistent state: `/var/lib/dh_pve_app/`

The default instance identity is derived from `/etc/machine-id`, so multiple Proxmox hosts do not collide.

## Runtime model

Collectors poll Proxmox/Linux locally. MQTT state is published for meaningful metric deltas, discrete events, inventory changes, collector failure/recovery, reconnect restoration, or a manual refresh. Process/MQTT liveness uses retained availability plus MQTT LWT.

A failure in one collector does not make unrelated subsystems unavailable. SMART reads are isolated per physical disk, and a disk is removed from inventory only after repeated authoritative scans confirm that it is absent.

Runtime polling/publish parameters can be adjusted from Home Assistant within application-defined hard limits. Infrastructure health policy remains Python-owned rather than being recalculated by Home Assistant templates.

## UPS / NUT architecture

The production ownership model is:

```text
UPS USB
  ↓
Proxmox
  ↓
NUT driver / upsd / upsmon PRIMARY / upssched
  ↓
Proxmox emergency shutdown policy
  ↓ read-only monitoring
DH PVE App
  ↓ MQTT Discovery
Home Assistant
```

Proxmox is the only physical UPS owner and the only authority that may initiate emergency shutdown of the host. Home Assistant does not issue FSD, does not shut down Proxmox, and does not edit the NUT shutdown policy.

The long-running `dh_pve_app.service` is deliberately **read-only with respect to `/etc/nut`**. Its systemd sandbox keeps `ProtectSystem=full` and does not grant `ReadWritePaths=/etc/nut`.

### NUT endpoint and UPS discovery

The default local NUT endpoint is:

```text
127.0.0.1:3493
```

The optional `[ups]` config section controls only the runtime NUT endpoint and command timeouts:

```ini
[ups]
host = 127.0.0.1
port = 3493
poll_interval_seconds = 5
command_timeout_seconds = 3
```

`DH PVE` always exposes:

- `button.dh_pve_scan_ups`
- `sensor.dh_pve_ups_scan_result`
- `sensor.dh_pve_ups_last_scan`

Pressing **Сканировать UPS** performs a read-only `upsc -l` query. One discovered UPS is persisted as the selected UPS. Zero, multiple, or failed scans never erase an existing selection.

When an UPS is selected, the same app process and MQTT connection publish the second logical device:

```text
DH PVE
DH PVE UPS
```

### UPS telemetry

Discovery is capability-driven. Only values reported by NUT are exposed. Normalized facts include, where supported:

- UPS status and raw NUT status tokens;
- battery charge, runtime and voltage;
- load;
- input/output voltage and frequency;
- nominal real power;
- warning/low battery thresholds;
- test result and beeper status;
- `ONBATT`, `LOW BATTERY`, overload, bypass, charging/discharging and replace-battery flags.

The app does not derive active watts from `load × nominal power`; some UPS models quantize low load too coarsely for that value to be trustworthy.

NUT is polled frequently but numeric MQTT publication remains sparse on line power and tighter on battery. Discrete power-state changes publish immediately. A NUT failure affects only `DH PVE UPS`; `DH PVE` monitoring continues.

## Emergency shutdown policy

NUT system files are treated as host configuration, not runtime application settings. They are configured during an explicit administrative commissioning operation and then observed read-only during normal service operation.

The expected managed policy is:

- `upsmon` role: `PRIMARY` on the Proxmox host;
- `SHUTDOWNCMD "/sbin/shutdown -h now"`;
- `POWERDOWNFLAG /etc/killpower`;
- `NOTIFYCMD /usr/sbin/upssched`;
- `ONBATT` starts the owned `dh-pve-ups-shutdown` timer;
- `ONLINE` cancels that timer;
- the timer invokes only the static DigitalHouses helper token, which calls `upsmon -c fsd`;
- native hardware Low Battery remains authoritative; no `ignorelb` or battery threshold overrides are installed.

The effective policy is read back from `/etc/nut/upsmon.conf`, `/etc/nut/upssched.conf`, `/etc/nut/ups.conf`, systemd state and NUT telemetry. Home Assistant receives diagnostic sensors such as:

- `sensor.dh_pve_ups_shutdown_policy`
- `sensor.dh_pve_ups_policy_on_battery_delay`
- `sensor.dh_pve_ups_policy_power_restore_delay`
- `sensor.dh_pve_ups_shutdown_delay`
- `sensor.dh_pve_ups_start_delay`

These entities are **read-only**. There is no MQTT/Home Assistant Apply button and no writable shutdown-policy number entity.

### Explicit commissioning

Commissioning is a rare root-only host operation. It is not invoked by the daemon and cannot be triggered over MQTT.

Example for a 30-minute ONBATT wait and 120-second UPS restore delay:

```bash
cd /opt/digitalhouses/dh_pve_app
.venv/bin/python -m app.main \
  --config /etc/dh_pve_app/dh_pve_app.conf \
  --state-dir /var/lib/dh_pve_app \
  --ups-policy-commission \
  --on-battery-delay-minutes 30 \
  --power-restore-delay-seconds 120
```

Before writing anything, commissioning requires root, a selected UPS, stable line power, and no running battery test. It calculates the Proxmox guest-shutdown budget, validates the draft, writes NUT files transactionally, restarts the UPS driver, waits for the exact effective restore delay reported by the hardware, and only then starts/restarts `nut-monitor`.

Managed NUT files are written with mode `0640` and the owner/group inherited from `/etc/nut` (normally `root:nut`). Rollback restores file contents, mode, owner and group.

A read-only commissioning report remains available separately:

```bash
cd /opt/digitalhouses/dh_pve_app
.venv/bin/python -m app.main \
  --config /etc/dh_pve_app/dh_pve_app.conf \
  --state-dir /var/lib/dh_pve_app \
  --ups-policy-preflight
```

## Shutdown history and readiness

The app keeps dry facts about Proxmox shutdowns; notification wording remains a Home Assistant responsibility. A real host boot is identified by the kernel `boot_id`, so restarting or upgrading `dh_pve_app` during the same boot does not create a false Proxmox boot event.

Shutdown history is persisted in `/var/lib/dh_pve_app/shutdown_history.json`. Up to 50 cycles are retained locally and the most recent 10 are exposed through MQTT. For the previous boot the app publishes:

- `shutdown_class`: `normal`, `unclean`, or `ups_power`;
- `shutdown_reason`: a more specific dry cause such as `shutdown`, `no_clean_shutdown`, `on_battery_fsd`, or `low_battery_fsd`;
- `shutdown_clean`: whether a clean host shutdown marker was actually observed, kept separate from the cause;
- outage/FSD/guest/host timestamps and derived timing intervals when available;
- UPS status, battery charge/runtime and load captured when FSD is first observed;
- per-VM/LXC shutdown start/end, duration, timeout, timeout ratio, result and forced/timeout state.

An unclean boot is never automatically called a power failure. `ups_power` requires confirmed UPS/FSD evidence; a manual/external FSD while the UPS remains on line power is kept distinct.

Home Assistant entities include:

- `sensor.dh_pve_previous_shutdown`
- `sensor.dh_pve_shutdown_history`
- `sensor.dh_pve_vm_<id>_shutdown`
- `sensor.dh_pve_lxc_<id>_shutdown`
- `sensor.dh_pve_ups_guest_shutdown_budget`
- `sensor.dh_pve_ups_shutdown_readiness`

Guest configuration is diagnostic-only. The app reads `onboot`, `startup.order` and `startup.down`; when `down` is absent, the effective Proxmox timeout is treated as 180 seconds. It never rewrites VM/LXC startup or shutdown settings.

UPS shutdown readiness checks the production NUT path as well as guest history. It warns on a forced/timeout guest, a guest that consumed at least 80% of its previous timeout, an unavailable shutdown budget, a broken NUT PRIMARY/upssched path, or an UPS-triggered shutdown that did not reach a clean PVE shutdown. Hosts without a selected UPS report readiness as `skip` rather than an error.

## Battery tests

Battery tests are runtime UPS operations and are intentionally separate from shutdown-policy configuration. Capability permitting, Home Assistant may expose:

- `button.dh_pve_ups_test_quick`
- `button.dh_pve_ups_test_deep`
- `button.dh_pve_ups_test_stop`

The built-in scheduler supports separate Quick and Deep intervals/times, with Deep priority when both are due. Before an automatic test the runtime verifies that NUT is available, the UPS is on line power, no fault/bypass/charge-discharge condition blocks the test, FSD is absent, and another battery test is not already running.

Default schedule:

- Quick: every 30 days at 12:00 local PVE time;
- Deep: every 180 days at 13:00 local PVE time.

Test history is retained in application state and exposed through MQTT Discovery.

## Guest and passthrough topology

The app discovers Proxmox guests automatically; no site-specific VM/LXC lists are required.

- A full topology scan runs at startup and on `button.dh_pve_refresh`.
- VM/LXC status uses one `/cluster/resources` query on a slower cadence.
- Guest configuration is normally read directly from pmxcfs under `/etc/pve/qemu-server` and `/etc/pve/lxc`.
- Guest start transitions trigger targeted rescans.
- VM `hostpciN` PCI passthrough is detected and cached.
- Existing LXC shared `/dev/dri` GPU ownership remains supported.
- VM/LXC Home Assistant entities are read-only status/diagnostic entities.

For storage-class PCI passthrough, a running VM with QEMU Guest Agent can be inspected with `lsblk`; eligible physical disks then reuse the same SMART, stable-ID, health and daily-statistics pipeline as host-local disks.

## Storage and disk health

Storage entities use **used / total** semantics. Home Assistant receives ready-to-display `usage_percent`, `used_gib`, and `total_gib` values.

Disk health is computed by the Python agent and exposed as exactly:

- `HEALTHY`
- `WARNING`
- `CRITICAL`

The health engine evaluates SMART overall state, NVMe critical warnings, wear, media/reallocated/pending/uncorrectable errors, unsafe-shutdown growth, temperature and counter growth. Home Assistant does not recompute these infrastructure decisions.

## Manual refresh

PVE:

- `button.dh_pve_refresh`
- `sensor.dh_pve_last_refresh`

UPS:

- `button.dh_pve_ups_refresh`
- `sensor.dh_pve_ups_last_refresh`

UPS refresh is independent of the full Proxmox topology refresh.

## Home Assistant package

Use one package for the entire application:

```text
dh_pve_app/examples/packages/dh_app_pve_package.yaml
```

Recorder includes `sensor.dh_pve_*` and `binary_sensor.dh_pve_*`, so PVE and UPS telemetry share one namespace. `number.dh_pve_ups_*` and `time.dh_pve_ups_*` are included for battery-test scheduler history. A separate UPS Recorder package is not required.

## Dashboards

PVE view:

```text
dh_pve_app/examples/dh_pve_dashboard.yaml
```

UPS view:

```text
dh_pve_app/examples/dh_pve_ups_dashboard.yaml
```

Reusable shutdown/readiness card:

```text
dh_pve_app/examples/dh_pve_shutdown_readiness_card.yaml
```

The UPS dashboard includes live UPS state, power/battery metrics, effective shutdown policy, NUT diagnostics, battery-test controls/schedule, history graphs and event log. Shutdown-policy controls are intentionally absent. The shutdown/readiness card shows the previous host shutdown cause/result, timing chain, UPS readiness/budget when an UPS exists, and dynamic per-VM/LXC shutdown diagnostics.

The PVE dashboard requires Mushroom, auto-entities, mini-graph-card and Entity Progress Card. The UPS view requires Mushroom and mini-graph-card. The reusable shutdown/readiness card requires Mushroom and auto-entities.

## Installation

Run on Proxmox as `root`:

```bash
curl -fsSL https://raw.githubusercontent.com/DigitalHouses/home-assistant-apps/main/dh_pve_app/install.sh | bash
```

The installer deploys the application, helper and systemd service. It does **not** silently commission NUT shutdown policy. Commissioning is an explicit post-install administrative action when physical UPS access and validation are available.

Existing valid application configuration is preserved on upgrades. Legacy `ups.policy_apply_enabled` lines are ignored for upgrade compatibility and no longer grant any runtime capability.

The service intentionally runs as root because SMART, `/etc/pve` guest configuration and passthrough inspection require host privileges; systemd still prevents the long-running daemon from modifying protected system configuration such as `/etc/nut`.

## Validation

Basic application diagnostics:

```bash
systemctl status dh_pve_app --no-pager
journalctl -u dh_pve_app -n 100 --no-pager
```

NUT source diagnostics:

```bash
upsc -l 127.0.0.1:3493
upsc ups@127.0.0.1:3493
```

A safe physical mains-loss commissioning test should first prove `OL → OB → OL` and `upssched` timer start/cancel without waiting for FSD. A full FSD/shutdown test belongs only after all intended NUT SECONDARY clients have been configured and verified.

## Status

`0.2.0-alpha` currently provides production-oriented Proxmox monitoring, NUT-backed UPS telemetry, capability-driven battery tests, explicit NUT shutdown-policy commissioning, persistent boot/shutdown history, guest shutdown diagnostics, UPS shutdown readiness, read-only policy observability in Home Assistant, and systemd-enforced separation between normal runtime and host configuration.
