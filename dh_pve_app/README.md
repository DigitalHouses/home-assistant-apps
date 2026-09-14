# DH PVE App

`dh_pve_app` is the DigitalHouses native Linux agent for Proxmox VE. It collects host, CPU, memory, storage, physical-disk/SMART, GPU/transcoding, fan, VM/LXC and passthrough topology data and publishes normalized Home Assistant entities through MQTT Discovery. The same process can monitor a locally connected UPS through Network UPS Tools (NUT).

Version `0.3.0` is the current stable release. It introduces the adaptive MQTT/Recorder presentation layer validated on the production Proxmox host while preserving the existing Proxmox-owned UPS shutdown architecture. Proxmox/NUT owns the UPS and every emergency-shutdown decision; Home Assistant is an observability and control surface, not the shutdown-policy authority.

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

Collectors keep their raw polling cadence and internal data model. The MQTT/Home Assistant presentation layer is separate: raw samples feed independent resource-local presentation groups, continuous numeric telemetry is averaged before publication, and discrete/state/event changes bypass averaging when they matter.

The goals are:

- smooth useful history instead of raw jitter;
- fewer Recorder writes;
- detailed history only for the resource that is actually loaded or in trouble;
- no global high-load mode that accelerates unrelated entities;
- simple broad Recorder globs without per-entity exclusions;
- a manual Refresh that still returns factual current values.

A failure in one collector does not make unrelated subsystems unavailable. SMART reads are isolated per physical disk, and a disk is removed from inventory only after repeated authoritative scans confirm it is absent.

### Raw collection versus HA publication

Collection and publication are deliberately different concepts.

Typical raw collection cadence remains:

- CPU / memory / fans: 10 s by default;
- guests: 30 s;
- GPU: 30 s;
- storage: 60 s;
- SMART / disk: 60 s by default;
- host inventory: 24 h;
- UPS: 5 s by default.

Home Assistant does not receive every raw numeric sample. Instead, each resource keeps a publication bucket and publishes an averaged point according to its current profile.

The default publication windows are:

| Profile | HA average window | Purpose |
|---|---:|---|
| `critical` | 30 s | maximum useful Recorder detail |
| `high` | 60 s | materially loaded / approaching a limit |
| `normal` | 600 s | ordinary operating history |
| `quiet` | 3600 s | very slowly changing telemetry |

The presentation layer never invents resolution. Effective publication cadence is never faster than the source collector cadence:

```text
effective_average_window = max(profile.average_window, source_collection_interval)
```

A 60-second SMART temperature collector therefore cannot produce genuine 30-second disk history even if that disk reaches `critical`.

### Decision windows and profiles

Profile decisions use rolling averages that are separate from publication buckets. A single raw spike does not normally change a profile.

Starting policy:

- CPU: 60 s decision window; load high/critical at 75/95%; temperature high/critical at 80/90 °C; CPU throttling is immediately `critical`;
- RAM: 120 s decision window; high/critical at 92/97%, so normal Linux memory usage around 70-90% does not create false alarms;
- each disk: independent 180 s temperature decision window using the same warning/critical limits as disk health;
- each GPU: independent 60 s window using temperature and transcoding/load where available;
- UPS: independent 30 s load decision window; On Battery/Bypass raises detail immediately, Low Battery/Overload is immediately `critical`.

Hysteresis is used for recovery so profiles do not chatter around thresholds.

CPU, RAM, every disk, every GPU and UPS are independent. A busy CPU does not make GPU, disks or UPS publish faster; one hot NVMe does not accelerate another disk.

### Independent retained MQTT groups

The monolithic state payload is no longer the production publication unit. Recorder-facing state is split into retained groups such as:

```text
.../<instance>/state/host
.../<instance>/state/cpu
.../<instance>/state/memory
.../<instance>/state/storage/<id>
.../<instance>/state/disk/<id>/telemetry
.../<instance>/state/disk/<id>/status
.../<instance>/state/gpu/<id>/telemetry
.../<instance>/state/gpu/<id>/status
.../<instance>/state/fans
.../<instance>/state/fan/<id>
.../<instance>/state/guest/vm/<id>
.../<instance>/state/guest/lxc/<id>
.../<instance>/state/guest/summary
.../<instance>/state/topology
.../<instance>/state/shutdown
.../<instance>/state/collector/<name>
.../<instance>/state/diagnostics

.../<instance>/ups/state/telemetry
.../<instance>/ups/state/status
.../<instance>/ups/state/config
.../<instance>/ups/state/tests
.../<instance>/ups/state/diagnostics
```

Publishing one group must not refresh unrelated Home Assistant entities. During upgrade from the old monolithic contract, retained `.../<instance>/state` and `.../<instance>/ups/state` payloads are tombstoned so stale broker data does not survive the migration.

Continuous sensors keep only stable metadata as Recorder attributes. Volatile values such as RAM `used_gib` or storage `used_gib` are not attached to another continuous state merely as changing attributes.

### Publication diagnostics

`DH PVE` exposes:

- `sensor.dh_pve_app_profile` — highest currently active resource profile with compact per-resource profile/reason attributes;
- `sensor.dh_pve_last_publication` — timestamp of the latest successful state-group publication with compact group/reason/profile metadata.

`DH PVE UPS` exposes the matching diagnostics:

- `sensor.dh_pve_ups_app_profile`;
- `sensor.dh_pve_ups_last_publication`.

These are diagnostics for verifying the adaptive presentation layer. Decision-window raw averages are intentionally not exposed as fast-changing attributes.

### Manual Refresh

PVE:

- `button.dh_pve_refresh`
- `sensor.dh_pve_last_refresh`

UPS:

- `button.dh_pve_ups_refresh`
- `sensor.dh_pve_ups_last_refresh`

A manual Refresh means “show me the current truth now”. It runs the applicable collectors and publishes all supported groups immediately. Numeric states may use the freshly collected current values for that explicit snapshot. Normal rolling decision history and publication buckets are preserved rather than reset. An isolated Refresh sample does not change a resource profile unless an immediate discrete critical condition is present.

UPS refresh is independent of the full Proxmox topology refresh.

### Runtime settings

Home Assistant runtime settings are limited to raw collector cadence controls that remain operationally useful:

- `number.dh_pve_fast_poll_interval`
- `number.dh_pve_disk_poll_interval`

The old `*_publish_delta` controls are retired. Publication thresholds/windows are App policy, not Home Assistant knobs. Existing persisted legacy delta values are ignored on upgrade, old MQTT set topics are safely ignored, and the removed MQTT Discovery components are tombstoned during migration.

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

The optional `[ups]` config section controls only runtime NUT access:

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

When a UPS is selected, the same application process and MQTT connection publish the second logical device, `DH PVE UPS`.

### UPS telemetry

Discovery is capability-driven. Only values reported by NUT are exposed. Normalized facts include, where supported:

- UPS status and raw NUT status tokens;
- battery charge, runtime and voltage;
- load;
- input/output voltage and frequency;
- nominal real power;
- warning/low battery thresholds;
- test result and beeper status;
- On Battery, Low Battery, overload, bypass, charging/discharging and replace-battery flags.

The canonical HA runtime entity is `sensor.dh_pve_ups_battery_runtime_minutes`. Raw runtime seconds may remain inside the App payload for internal/backward compatibility but are not exposed as a duplicate Recorder entity.

The App does not derive active watts from `load × nominal power`; some UPS models quantize low load too coarsely for that value to be trustworthy.

UPS numeric telemetry is averaged through the same adaptive presentation model while discrete power-state transitions remain immediate. A NUT failure affects only `DH PVE UPS`; PVE monitoring continues.

## Emergency shutdown policy

NUT system files are host configuration, not runtime application settings. They are configured during an explicit administrative commissioning operation and observed read-only during normal service operation.

The expected managed policy is:

- `upsmon` role: `PRIMARY` on the Proxmox host;
- `SHUTDOWNCMD "/sbin/shutdown -h now"`;
- `POWERDOWNFLAG /etc/killpower`;
- `NOTIFYCMD /usr/sbin/upssched`;
- `ONBATT` starts the owned `dh-pve-ups-shutdown` timer;
- `ONLINE` cancels that timer;
- the timer invokes only the static DigitalHouses helper token, which calls `upsmon -c fsd`;
- native hardware Low Battery remains authoritative; no `ignorelb` or battery-threshold overrides are installed.

The effective policy is read from `/etc/nut/upsmon.conf`, `/etc/nut/upssched.conf`, `/etc/nut/ups.conf`, systemd state and NUT telemetry. Home Assistant receives read-only diagnostics including:

- `sensor.dh_pve_ups_shutdown_policy`
- `sensor.dh_pve_ups_policy_on_battery_delay`
- `sensor.dh_pve_ups_policy_power_restore_delay`
- `sensor.dh_pve_ups_shutdown_delay`
- `sensor.dh_pve_ups_start_delay`

There is no MQTT/Home Assistant Apply button and no writable shutdown-policy number entity.

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

Before writing anything, commissioning requires root, a selected UPS, stable line power and no running battery test. It calculates the Proxmox guest-shutdown budget, validates the draft, writes NUT files transactionally, restarts the UPS driver, waits for the exact effective restore delay reported by the hardware, and only then starts/restarts `nut-monitor`.

Managed NUT files are written with mode `0640` and owner/group inherited from `/etc/nut` (normally `root:nut`). Rollback restores content, mode, owner and group.

Read-only preflight:

```bash
cd /opt/digitalhouses/dh_pve_app
.venv/bin/python -m app.main \
  --config /etc/dh_pve_app/dh_pve_app.conf \
  --state-dir /var/lib/dh_pve_app \
  --ups-policy-preflight
```

## Shutdown history and readiness

The App stores factual Proxmox shutdown history; notification wording remains a Home Assistant responsibility. A real host boot is identified by kernel `boot_id`, so restarting or upgrading `dh_pve_app` during the same boot does not create a false PVE boot event.

History is persisted in `/var/lib/dh_pve_app/shutdown_history.json`. Up to 50 cycles are retained locally and the most recent 10 are exposed through MQTT.

For the previous boot the App keeps:

- `shutdown_class`: `normal`, `unclean`, `ups_power`, or `unknown`;
- `shutdown_reason`: observed cause only (`shutdown`, `on_battery_fsd`, `low_battery_fsd`, `manual_or_external_fsd`, or `unknown`);
- `shutdown_clean`: `true`, `false`, or unknown when evidence is insufficient;
- outage/FSD/guest/host timestamps and derived intervals only when evidence exists;
- UPS state captured when FSD is first observed;
- per-VM/LXC shutdown timing/result/timeout information.

Cause and result remain separate. An unclean boot is never automatically called a power failure. `ups_power` requires confirmed UPS/FSD evidence. Missing previous-boot evidence remains `unknown` rather than inventing timestamps or causes.

Home Assistant entities include:

- `sensor.dh_pve_previous_shutdown`
- `sensor.dh_pve_shutdown_history`
- `sensor.dh_pve_vm_<id>_shutdown`
- `sensor.dh_pve_lxc_<id>_shutdown`
- `sensor.dh_pve_ups_guest_shutdown_budget`
- `sensor.dh_pve_ups_shutdown_readiness`

Guest configuration is diagnostic-only. The App reads `onboot`, `startup.order` and `startup.down`; when `down` is absent, the effective Proxmox timeout is 180 seconds. The retained `state/shutdown` group carries a compact snapshot of those stable settings so shutdown-history entities remain self-contained after MQTT group splitting. The App never rewrites VM/LXC startup/shutdown settings.

UPS shutdown readiness warns on forced/timeout guests, near-timeout guests, an unavailable shutdown budget, a broken NUT PRIMARY/upssched path, or a UPS-triggered shutdown whose host clean/unclean result failed or is unknown. Hosts without a selected UPS report readiness as `skip`.

## Battery tests

Battery tests are runtime UPS operations and remain separate from shutdown-policy configuration. Capability permitting, Home Assistant may expose:

- `button.dh_pve_ups_test_quick`
- `button.dh_pve_ups_test_deep`
- `button.dh_pve_ups_test_stop`

The scheduler supports separate Quick and Deep intervals/times, with Deep priority when both are due. Before an automatic test the runtime verifies that NUT is available, the UPS is on line power, no fault/bypass/charge-discharge condition blocks the test, FSD is absent, and another battery test is not already running.

Default schedule:

- Quick: every 30 days at 12:00 local PVE time;
- Deep: every 180 days at 13:00 local PVE time.

Test history is retained in application state and exposed through MQTT Discovery.

## Guest and passthrough topology

The App discovers Proxmox guests automatically; no site-specific VM/LXC lists are required.

- full topology scan at startup and on `button.dh_pve_refresh`;
- VM/LXC status through one `/cluster/resources` query on the slower cadence;
- guest configuration normally read directly from pmxcfs under `/etc/pve/qemu-server` and `/etc/pve/lxc`;
- targeted rescan when a guest transitions to `running`;
- VM `hostpciN` PCI passthrough detection and caching;
- existing LXC shared `/dev/dri` GPU ownership support;
- read-only VM/LXC HA status/diagnostic entities.

For storage-class PCI passthrough, a running VM with QEMU Guest Agent can be inspected with `lsblk`; eligible physical disks reuse the same SMART, stable-ID, health and daily-statistics pipeline as host-local disks.

## Storage and disk health

Storage UI uses **used / total** semantics. Storage usage itself is averaged for Recorder-facing publication; stable capacity/type metadata remains available without attaching changing raw usage attributes to unrelated states.

Disk health is computed by Python and exposed as exactly:

- `HEALTHY`
- `WARNING`
- `CRITICAL`

The health engine evaluates SMART overall state, NVMe critical warnings, wear, media/reallocated/pending/uncorrectable errors, unsafe-shutdown growth, temperature and counter growth. Home Assistant does not recompute infrastructure health.

## Home Assistant package

Use one package for the entire application:

```text
dh_pve_app/examples/packages/dh_app_pve_package.yaml
```

The package is intentionally simple and Recorder-only. It keeps broad includes:

```text
sensor.dh_pve_*
binary_sensor.dh_pve_*
number.dh_pve_ups_*
time.dh_pve_ups_*
```

Publication/profile thresholds do not live in HA `input_number` helpers. The previous six unused threshold helpers and their startup initializer were removed so there is one source of truth: the App policy.

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

The PVE dashboard requires Mushroom, auto-entities, mini-graph-card and Entity Progress Card. The UPS view requires Mushroom and mini-graph-card. The reusable shutdown/readiness card requires Mushroom and auto-entities.

## Installation

Run a stable release on Proxmox as `root`:

```bash
curl -fsSL https://raw.githubusercontent.com/DigitalHouses/home-assistant-apps/main/dh_pve_app/install.sh | bash
```

For a pre-merge feature/ref deployment, installer and application source must come from the **same ref**:

```text
REF=<ref>
DIGITALHOUSES_SOURCE_REF="$REF" \
  bash <(curl -fsSL "https://raw.githubusercontent.com/DigitalHouses/home-assistant-apps/$REF/dh_pve_app/install.sh")
```

The installer deploys the App, helper and systemd service. It does **not** silently commission NUT shutdown policy. Existing valid application configuration is preserved. Legacy `ups.policy_apply_enabled` is ignored for upgrade compatibility and does not grant runtime capability.

The service runs as root because SMART, `/etc/pve` guest configuration and passthrough inspection require host privileges; systemd still prevents the long-running daemon from modifying protected host configuration such as `/etc/nut`.

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

Release/deploy validation is non-destructive. Verify service/MQTT health, grouped retained topics, NUT telemetry and the read-only policy preflight. If mains behavior is checked physically, stop at `OL → OB → OL` and confirm the `upssched` timer start/cancel before any FSD threshold. Do not invoke `upsmon -c fsd`, wait for the emergency shutdown timer to expire, or intentionally shut down the host as part of release validation.

## Status

`0.3.0` is the current stable release. Its production contract is resource-local averaged publication, independent retained MQTT groups, PVE/UPS profile diagnostics, Recorder-safe attributes, migration cleanup for retired delta controls and monolithic retained topics, a self-contained shutdown diagnostics group, and a Recorder-only HA package while preserving the Proxmox/NUT shutdown-safety architecture.
