# UPS Runtime Read-Only Architecture

## Goal

Make `dh_pve_app` permanently read-only with respect to `/etc/nut` during normal service operation. NUT shutdown configuration is an explicit administrative commissioning action, not a Home Assistant/MQTT runtime feature.

## Runtime contract

- The systemd service never receives write access to `/etc/nut`.
- MQTT Discovery exposes UPS/NUT shutdown policy only as read-only sensors/attributes.
- MQTT does not subscribe to policy set/apply topics and ignores messages sent to legacy policy command topics.
- `UpsRuntime` reads the effective NUT policy from host files and publishes what is actually configured; it does not keep a mutable policy draft or call an applier.
- Battery-test controls and battery-test schedule controls remain runtime features.

## Commissioning contract

- Configuration is performed only by an explicit root CLI invocation: `--ups-policy-commission`.
- Commissioning validates that the UPS is on stable line power and no battery test is running before changing NUT configuration.
- The existing transactional renderer/applier is reused outside the daemon.
- Managed NUT files are written atomically with the owner/group of `/etc/nut` (production: `root:nut`) and mode `0640`; rollback restores the previous file snapshot.
- Commissioning may be rerun deliberately for rare administrative changes, but it is never triggered by MQTT or Home Assistant.

## Observability

The read-only shutdown policy publishes the effective values parsed from the NUT files, including:

- role and `nut-monitor` state;
- shutdown enabled/disabled;
- ONBATT shutdown wait;
- UPS power-restore delay (`ondelay`);
- upssched presence/rules;
- PVE guest shutdown budget when available.

## Compatibility

Existing configs containing `policy_apply_enabled` remain loadable; the key is ignored. Old MQTT policy controls are removed through normal Discovery tombstones after the updated runtime republishes Discovery.
