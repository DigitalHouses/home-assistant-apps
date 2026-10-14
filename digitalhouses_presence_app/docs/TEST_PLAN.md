# Presence App — staged implementation and acceptance plan

## Stage 0 — read-only audit

- Inspect the installed `dh_presence_ws_test` custom integration and Lovelace resource on the user's **home** Home Assistant (not Amir).
- Record WebSocket command namespace, available Companion devices/GPS tracker bindings, active network interfaces, MQTT discovery collisions, and current backups.
- Reuse the proven experimental WebSocket / ARP code rather than invent a second implementation.

## Stage 1 — isolated engine / registration tests

- WebSocket authenticated HA user, direct LAN peer IP, active ARP MAC; fail for Cloudflare/Tailscale, wrong user/device selection and authorization failure.
- Prove whether an App-hosted engine can use ARP/raw sockets and LAN L2 access with minimal privileges. If not, compare a Core-only implementation.
- iPhone Wi-Fi on, screen locked continuously **15+ minutes**, no Companion foreground activity; record misses and longest gaps.
- Wi-Fi toggled in iOS settings, DHCP IP changed, private Wi-Fi MAC rotated, AP roaming; confirm safe reacquisition.
- Simulate scanner error, access denied and MQTT disconnect — NONE should translate unknown into not_home.

## Stage 2 — pure product logic

- GPS/Wi-Fi/Hybrid decisions including contradictory sources.
- Verified negative Wi-Fi evidence for a continuous configured timeout (15 minutes initial); ordinary ARP timeouts never qualify.
- Durable logical state under source loss, restart and corrupted persistence. Never initial OFF from unknown.
- No fake `arrival/departure` at startup; exactly one transition when truly confirmed.
- MQTT: one Device, dynamic resident discovery, stable identities, tombstone removal, retained state ordered before non-retained event.
- Distance Haversine validity and freshness with Recorder (no duplicate attribute history).
- Machine event schema validation, notification package trigger routing, status-card conventions.

## Stage 3 — safe pilot

- **Implemented in experimental GPS pilot 0.1.0:** runnable App Dockerfile, config, run script, translations, icon/logo, implementation marker, product validator, registry, CI and MQTT transport. **Pending:** production immutable release pipeline integration, live HA acceptance, Core WebSocket registration adapter, Wi-Fi engine and standard status-card operations.
- Install only on owner's home HA `192.168.11.33:80` after comparing prior experiment and preserving rollback.
- Exercise state loss/recovery, source contradiction, restart, long sleep and actual mobile registration.
- Alarm automation remains **disconnected** until a separate security-oriented acceptance.

## Git workflow

Changes must be made in this repository by feature branch → PR → full CI → normal merge. No direct writes to production HA or `main`. Do not create any additional product repository for Presence.

## Stage 4 — registration bridge CI + on-site acceptance (0.1.11)

- CI: authenticator must use `connection.user` and `connection.remote`; backend candidate list uses one `mobile_app` entry and its `device_tracker` for the same HA user only; no user IP/MAC supplied by browser.
- CI: App registration save/load schema, duplicate device/MAC rejection, owner name, exclusion by HA User ID, no synthetic arrivals, old entities stable, safe ARP route/probe handling.
- Field acceptance **pending**: Core bridge installation and WebSocket command availability; App token GET/POST 200 from authenticated bridge; on-link interface `enp6s18` or detected LAN; real ARP reply; selected iPhone vs same-account iPad; Cloudflare rejection; DHCP change/private MAC rotation; no duplicate MQTT Discovery or events.
- Do not merge field acceptance into a statement that Wi-Fi Engine works: enrollment ARP is a **one-off attestation**, not a continuous presence sensor.
