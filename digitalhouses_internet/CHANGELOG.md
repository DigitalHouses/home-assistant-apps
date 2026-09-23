# Changelog

## 0.1.0

- Created DigitalHouses Internet App as a new Home Assistant App product.
- Added canonical `dh_internet_app_` MQTT/Home Assistant identity.
- Added Internet/router availability and current-month outage persistence.
- Added `smart` and `both` recovery modes.
- Limited recovery actions to Home Assistant `button` and `switch` entities.
- Added guarded switch power restoration, recovery countdown, Stop control and structured events.
- Added Version and Started-at runtime diagnostics.
- Added Ookla Speedtest runtime with periodic and manual execution.
- Added Download, Upload, Ping, Jitter, Packet loss and compact Speedtest status entities.
