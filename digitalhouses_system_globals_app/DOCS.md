# DigitalHouses System Globals

Experimental App. Before first start, migrate the existing Night Mode publisher:
disable the old package publication after exporting its settings, and verify there
is only one authoritative publisher of DigitalHouses/Global/night_mode/state.
Never run two publishers concurrently. The App starts manually on a new installation
to permit this migration. It is not a replacement for DH Presence.

The Ingress administrator sets the mode, local schedule and independent day/night
profiles. Unconfigured values are unset. Select CCT or RGB and set exactly one color.
The MQTT HA owner controls use the same store; the atomic color text is
cct:4000 or rgb:#FF5000 (empty clears the color). HA Core restart does not stop
the App schedule. A complete HAOS restart does.

Readiness uses an MQTT roundtrip, an actual HA MQTT sensor update checked through
the read-only Core API, and live correlated Zigbee2MQTT health response plus bridge
inventory for every automatically discovered Zigbee2MQTT bridge on the connected
MQTT broker, including nested base topics. No base-topic setting is required.
All discovered bridges must be healthy; if none are discovered, Zigbee Ready is off.
Retire a bridge by clearing its retained state/info/devices topics. The Ingress lists
discovered bridge names and readiness. Optional components can be excluded from System Ready in App options.
Readiness is not proof that every individual device is available.
When MQTT or producer is lost, gates must be treated as closed. The public retained
gate states are accompanied by a non-retained lease at
DigitalHouses/digitalhouses_system_globals_app/readiness/lease (QoS 1, every 5 s,
20 s validity). HA gates consume the lease, not stale retained on. Direct
consumers require current publisher availability and a fresh session lease.
MQTT connection failure cannot send a new state through that same failed broker.
Lifecycle reports observed states only; lost API is not proof of a shutdown.

The owner View is published at dashboards/ru/10_system_globals.yaml, path
system-globals. Placement in a non-admin panel is configured by DH Sync, not this App.
The Recorder package is separate. The compact control card uses Mushroom and
custom:button-card >=5.0; no private notifications are required.

Telemetry: the official App configuration defaults to telemetry_enabled=false.
Review the [product telemetry policy](../docs/standards/PRODUCT_TELEMETRY_POLICY.md)
and [legal review](../docs/standards/TELEMETRY_PRIVACY_LEGAL_REVIEW.md). Explicit
acceptance is required by the repository activation model. No telemetry is sent
before acceptance; transport failure does not block core runtime after acceptance.
The payload is the product name, version and random installation identity
plus protocol metadata; no profile, household, device or MQTT data.
Public rollout of mandatory telemetry remains subject to the repository legal gate.
