# Development and release readiness — 0.1.5

The implementation is an experimental candidate. Do not connect to a production
broker while the legacy Night Mode publisher is active. First start is manual to
allow controlled migration; enable Start on boot only after validating the new owner.

## Tests

From the product directory with Python 3.11+ and isolated dependencies:

```sh
python3 -m pip install -r requirements.txt
PYTHONPATH=rootfs/app python3 -m unittest discover -s tests -v
DH_TEST_MOSQUITTO=/path/to/mosquitto PYTHONPATH=rootfs/app python3 -m unittest discover -s tests -v
```

The integration tests launch a dedicated loopback-only Mosquitto, a simulated HA
REST server and Z2M MQTT actor. No production broker or installation is required.
The standalone development entrypoint accepts an explicit host, port and state file:

```sh
python3 rootfs/app/runtime.py --host 127.0.0.1 --port 18883 --state /tmp/system-globals-test/state.json
```

This entrypoint exercises only autonomous Modes and Profiles. The HAOS entrypoint
is rootfs/app/service.py. Both share the same authoritative core. MQTT 5 is
required to preserve the sender's retain flag and reject retained commands.
On reconnect a fresh client is used; missed transient events are not replayed.

## Decisions and limitations

- Day/night profiles store independent CCT and RGB values. HA exposes two text
  controls (kelvin and #RRGGBB), Ingress exposes temperature and RGB picker.
  The owner/admin Views pair each profile setting in two columns using Mushroom.
  The common Package exposes two native template lights as RGB configuration
  controls; the existing text entities remain authoritative. Generic on/off
  commands are intentionally no-ops; clear is an explicit text command. The
  unset color uses a white preview and is identified by the separate Clear RGB
  status. Do not assign these configuration lights to physical lighting groups
  or Electrica targets. If the Package is not loaded, the UI reports the helper
  as unavailable; verify DH Sync package installation and reload template YAML.
  Consumers choose the supported mode per device, not per global profile.
  Storage schemas 1 and 2 migrate to schema 3 automatically, dropping only
  obsolete selectors and display/indicator brightness fields. Restore a
  pre-upgrade backup before downgrading. Ingress uses a color picker with clear action.
- A live non-retained readiness lease is published every 5 s with a 20 s expiry.
  Direct consumers must use this and producer availability, not stale retained on.
  Positive HA evidence requires an actual MQTT probe value observed through the
  read-only HA API. Z2M requires inventory plus a correlated health response.
- HA Lifecycle records only directly observed transitions. API loss alone never
  establishes a clean/unclean shutdown. Exact HA startup/stop and downtime may
  remain unknown. No guessed timestamps or fabricated unexpected-shutdown event.
- No changes to other product code or DH Sync panel composition. The owner View
  must be placed in a non-admin panel by the DH Sync project.
- Full installed HAOS, actual Zigbee2MQTT, UI rendering, real restart and migration
  acceptance remain separate from DEV simulation. Build/publish of the versioned
  OCI image is subject to the normal repository release workflow.
- The repository's telemetry policy requires affirmative activation and has an
  explicit outstanding mandatory public-rollout legal gate. Do not treat this
  technical candidate as confirmation of legal clearance.


## DH Lib UI pilot (0.1.12)

The pinned 0.1.0 CSS/JS are bundled under rootfs/app/dh_lib_ui; hashes and source
commit are in dh-lib-ui.lock.json. UI assets use the existing authorized Ingress
server. HA/MQTT status comes from readiness evidence; Telemetry reports the last
completed heartbeat of this process, not mere consent. DH Sync receipt is
unknown (the existing retained announcement has no acknowledgement contract).
The HA timezone row is read-only; the existing schedule timezone remains an
independent, unchanged setting. Theme is a browser-local preference. DEBUG and
telemetry consent are read-only here (configured through HA App options).
Restart/install actions are omitted because this App does not expose them.
The main workspace and settings are mounted once; Journal/Toast remain independent.
Run the existing Chromium test on DEV; production Ingress/theme validation is
still required before accepting the shared library's pilot.
