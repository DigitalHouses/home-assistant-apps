# Guided USB UPS / NUT setup (draft)

This implementation is prepared for **DigitalHouses HOME with one local USB UPS**.
The Home Assistant view is a preview and must not be installed on a production
host before a field commissioning test. Existing SNMP/network UPS configurations
are read-only to this wizard.

## Home Assistant interface

The PVE device publishes setup status even when NUT is not installed or no UPS
has been selected:

- `sensor.dh_pve_agent_ups_setup` – one retained setup snapshot with USB
  manufacturer/model, Bus/Device, VID:PID, NUT driver/service, PRIMARY,
  monitor, shutdown readiness, errors and operation outcome;
- `select.dh_pve_agent_ups_driver` – select an available local NUT driver;
- `button.dh_pve_agent_ups_setup_install` – install NUT packages only;
- `button.dh_pve_agent_ups_setup_driver` – configure the selected USB driver;
- `button.dh_pve_agent_ups_setup_server` – repair NUT Server;
- `button.dh_pve_agent_ups_setup_primary` – configure local NUT PRIMARY;
- `button.dh_pve_agent_ups_setup_monitor` – start NUT Monitor;
- `button.dh_pve_agent_ups_setup_activate` – activate host shutdown.

Each action has a matching diagnostic binary sensor
`binary_sensor.dh_pve_agent_ups_setup_can_<stage>` for built-in
Lovelace conditional visibility. Only one stage can execute at a time.

Preview v8: `examples/dashboard-preview/11_pve_ups_preview_v8.yaml`.

**Updated UI preview v9:** `examples/dashboard-preview/11_pve_ups_preview_v9.yaml`.
Each diagnostic row has an inline compact Mushroom action chip. Dependent
steps are shown with a locked, non-clickable action until prerequisites
are met, instead of being hidden. Full-width button cards are removed.
The green and repair cards are mutually exclusive. The current PVE shutdown
history, VM/LXC table and shutdown-tree rendering are retained; if history is
empty, the view shows the *planned* shutdown sequence instead.

## Local execution

Only a fixed MQTT `PRESS` command is accepted for each stage. Retained
commands and arbitrary shell arguments are rejected. The normal PVE monitoring
service keeps `ProtectSystem=full` and does not write `/etc/nut`.

Each accepted stage runs in the root-owned systemd oneshot:
`digitalhouses_pve_agent-ups-setup@<stage>.service`.
It is never enabled at boot. It validates the current hardware/state again
before changing anything. Result and failure are published through
`sensor.dh_pve_agent_ups_setup` attributes.

Allowed order: USB → install NUT → driver → NUT Server → PRIMARY →
NUT Monitor → activate shutdown. Each stage changes only its own settings.

The primary setup generates a private credential and leaves
`SHUTDOWNCMD "/bin/true"` until the final activation step. The latter
requires OL, working monitor, full existing preflight (except the deliberately
disabled SHUTDOWNCMD), and makes *only* the approved replacement
`SHUTDOWNCMD "/sbin/shutdown -h now"`. Neither this service nor its GUI
issues FSD, guest-stop commands, UPS output commands, or a live shutdown test.

NUT configs are backed up under
`/var/lib/digitalhouses_pve_agent/nut_setup_backups/`.
Failure during apply attempts rollback; a package-install failure or an
interrupted systemd process may still need administrator inspection.
No arbitrary existing multi-UPS, SNMP or custom remote setup is overwritten.

## Readiness and limitations

- The USB identifier uses Linux sysfs and a conservative set of known
  UPS vendors/product labels. If a device is not identifiable, setup remains
  blocked rather than treating an arbitrary USB peripheral as an UPS.
- Bus/Device addresses are diagnostic and may change after unplug/reboot.
  The serial number, when exposed by the device, is also published.
- Initial NUT package installation uses APT but does not upgrade the whole
  Proxmox host. Package post-install steps may manipulate systemd services.
- The driver list is derived from installed NUT executables, with a minimal
  fallback before installation.
- No hardware/live power-loss test has yet been performed. Do not merge or
  deploy until a representative USB UPS has been used to verify the
  commissioning path and rollback.
- Existing UPS telemetry, trigger policy, PVE shutdown history and shutdown
  ordering remain unchanged. HA and MQTT are not on the safety shutdown path.

### v0.5.101 prerelease follow-up

After `nut-server.service` starts or restarts, the setup oneshot accepts
only a *fresh* verified `OL` status. It retries transient empty/failed
`upsc` responses for at most 12 seconds, but aborts immediately for an
explicit unsafe status. No automatic retry is performed on battery power.

### UPS Dashboard Preview v10

The VM/LXC planned shutdown tree now renders independently of shutdown
history. If the budget sequence is temporarily absent, the view can
reconstruct the ordered tree from per-guest shutdown sensors. Historical
shutdown entries are kept in their own expandable section. Changes are
limited to the preview YAML; no NUT/Agent update is necessary.

Preview file: `examples/dashboard-preview/11_pve_ups_preview_v10.yaml`.

### UPS Dashboard Preview v11 — planned tree correction

The original shutdown_sequence is a collection of *currently running*
VM/LXC IDs grouped by the same configured startup.order, processed in
reverse order. It is not a history or a sequence of synthetic numbered
stages. Preview v11 renders actual per-guest kind, VMID, and display name
from the existing shutdown entities, retaining that grouping and order.
It does not claim those guests shut down concurrently. An absent running
sequence is not replaced with the unrelated list of onboot guests.
Historical shutdown events remain separately expandable, and all existing
UPS controls and tables are unchanged. Preview:
`examples/dashboard-preview/11_pve_ups_preview_v11.yaml`.
