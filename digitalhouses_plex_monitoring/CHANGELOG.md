# Changelog

## 0.1.3

- Detect Plex Transcoder input media from `-i` and ignore ffmpeg output formats such as `-f dash`.
- Remove opaque Plex item and section IDs from `current_item`.
- Support multiple simultaneous active media items.
- Add active-item attributes and `sensor.dh_plex_transcoder_count`.
- Publish immediately when the active media workload changes.

## 0.1.2

- Detect Plex Server, Scanner and Transcoder reliably when Linux truncates process names or Plex splits the executable name across argv.
- Use the same process-role detection for activity classification and CPU grouping.


## 0.1.1

- Use flat default MQTT namespace `DigitalHouses/Global/plex_monitoring`.
- Use `plex` as the non-interactive default instance ID and hostname as instance name.
- Fix virtualenv permissions for the unprivileged systemd service.
- Update `last_refresh` only after a successful manual refresh.


## 0.1.0

- Initial DigitalHouses Plex Monitoring Linux agent.
