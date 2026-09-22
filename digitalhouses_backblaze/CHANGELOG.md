# Changelog

## 0.1.0

- Initial DigitalHouses Backblaze Home Assistant App.
- Monitor every B2 bucket visible to the configured application key.
- Publish total stored bytes plus per-bucket stored bytes, current files, and stored versions through MQTT Discovery.
- Add API connectivity, last update, manual refresh, App version, and process started-at diagnostics.
- Use Backblaze B2 Native API v4 with listBuckets and listFiles capabilities only.
- Add opt-in DigitalHouses product telemetry, disabled by default, with persistent installation identity, 24-hour jittered heartbeat scheduling, failure isolation, and authenticated deletion.
