# DigitalHouses System Globals

Experimental App. Before first start, migrate the existing Night Mode publisher:
disable the old package publication after exporting its settings, and verify there
is only one authoritative publisher of DigitalHouses/Global/night_mode/state.
Never run two publishers concurrently. The App starts manually on a new installation
to permit this migration. It is not a replacement for DH Presence.

The Ingress administrator sets the mode, local schedule and independent day/night
profiles. Unconfigured values are unset. Set CCT and RGB independently in each profile. Both can coexist.
The MQTT HA owner controls use the same store; separate text entities accept
CCT in kelvin and RGB as #RRGGBB (empty clears only that value). Consumers
select the applicable device color mode. Existing profile values are migrated
without loss from storage schema 1 to 2; old exports can also be imported. Version 0.1.5 removes display/indicator
brightness, migrates to storage schema 3, and uses a color picker with a clear
action in Ingress instead of a visible HEX input. HA Core restart does not stop
the App schedule. A complete HAOS restart does.

Readiness uses an MQTT roundtrip, an actual HA MQTT sensor update checked through
the read-only Core API, and live correlated Zigbee2MQTT health response plus bridge
inventory for every automatically discovered Zigbee2MQTT bridge on the connected
MQTT broker, including nested base topics. No base-topic setting is required.
All discovered bridges must be healthy; if none are discovered, Zigbee Ready is off.
Retire a bridge by clearing its retained state/info/devices topics. The Ingress lists
discovered bridge names and readiness. MQTT and Home Assistant are always required
for System Ready. Only Zigbee2MQTT is optional via require_z2m (default true).
When false, discovery and health monitoring still run, but Zigbee Ready does not
block System Ready. Core schedule and profiles remain independent of HA readiness.
Readiness is not proof that every individual device is available.
When MQTT or producer is lost, gates must be treated as closed. The public retained
gate states are accompanied by a non-retained lease at
DigitalHouses/digitalhouses_system_globals_app/readiness/lease (QoS 1, every 5 s,
20 s validity). HA gates consume the lease, not stale retained on. Direct
consumers require current publisher availability and a fresh session lease.
MQTT connection failure cannot send a new state through that same failed broker.
Lifecycle reports observed states only; lost API is not proof of a shutdown.

The full administrative View is published at dashboards/ru/10_system_globals.yaml,
path system-globals. The owner View is dashboards/ru/20_system_globals_user.yaml,
path system-globals-user; it contains only mode, schedule, active settings, history
and profile controls. DH Sync places the owner View in the non-admin DH User panel.
This is UI separation, not a replacement for Home Assistant permissions.
Both Views use short, localized Lovelace row names rather than changing MQTT
entity names. Matching Russian and English YAML files are maintained under
dashboards/ru and dashboards/en, with the same View paths and entity IDs.
Current DH Sync reads dashboards/ru only; selecting the English resources
requires a separate DH Sync localization implementation. Do not publish both
languages into the same panel at once.
The Recorder package in packages/common/dh_system_globals_app.yaml includes
the authoritative night-mode switch (off = day, on = night). The View displays
its native 24-hour history graph; no additional sensor or automation is needed.
DH Sync installs the package and View from main; HA Recorder must load the
package before new state changes are recorded. Previously unrecorded states
cannot be reconstructed. The compact control card uses Mushroom and
custom:button-card >=5.0; no private notifications are required.

Telemetry: the official App configuration defaults to telemetry_enabled=false.
Review the [product telemetry policy](../docs/standards/PRODUCT_TELEMETRY_POLICY.md)
and [legal review](../docs/standards/TELEMETRY_PRIVACY_LEGAL_REVIEW.md). Explicit
acceptance is required by the repository activation model. No telemetry is sent
before acceptance; transport failure does not block core runtime after acceptance.
The payload is the product name, version and random installation identity
plus protocol metadata; no profile, household, device or MQTT data.
Public rollout of mandatory telemetry remains subject to the repository legal gate.

One immediate best-effort heartbeat is attempted at each activated App startup.
The same running process retries after one hour on failure, or sends its next
periodic heartbeat 24h ± 30 min after success. Restarts preserve identity and
credentials, but do not suppress the single startup attempt.

## LOG (0.1.6)

The LOG button opens the full-screen DH Journal. It retains the latest 3000 local SQLite events, survives App restarts, supports RU/EN, search, level filters and full UTF-8 .log export. DEBUG is optional in App configuration. No MQTT entities or Recorder changes are introduced.
