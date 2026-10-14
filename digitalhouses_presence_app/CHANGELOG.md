# Changelog

## 0.1.0

- First installable **experimental** Home Assistant App for development and pilot use.
- Supervisor configuration, local Docker build, MQTT broker discovery, version and started-at diagnostics.
- GPS input through Home Assistant Core REST API for explicitly configured Companion trackers.
- Retained per-resident and aggregate logical presence. Unknown/expired GPS data is not interpreted as absent.
- Individual GPS binary sensors and straight-line distance sensors, structured non-retained machine events.
- Durable last-confirmed presence across App restart, safe source freshness handling and MQTT resynchronization.
- Wi-Fi presence, trusted automatic Mobile Companion registration and App UI remain **unimplemented**, and are not used for absence decisions.
- Initial runtime does not connect to DigitalHouses telemetry (unreleased experimental pilot).
