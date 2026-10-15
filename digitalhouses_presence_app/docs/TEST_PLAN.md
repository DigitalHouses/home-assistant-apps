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

## Stage 4 — native Ingress registration CI + home acceptance (0.1.11)

- CI: only Supervisor `172.30.32.2` can reach the enrollment API,
  authenticated `X-Remote-User-Id` / `X-Remote-User-Display-Name`
  are required, and XFF uses the actual Core peer, never a spoofed
  client-controlled prefix.
- CI: direct local URL is required (no Cloudflare external hostname);
  validate all GPS source selections against Core states, disallow
  client-supplied user/IP/MAC, reject duplicate device/MAC,
  preserve durable private registry and excluded-user behavior.
- CI: ARP must be fresh, local, unambiguous and non-promoting to
  Wi-Fi presence. On error no resident registration.
- **Field pending:** Supervisor Ingress connects to App's port 8099
  in host-network mode; stable user identity and Core peer IP across
  direct LAN vs Cloudflare; container permissions for ARP and access
  only from Supervisor proxy; no false device binding with same-user
  iPhone+iPad; safe App upgrade/rollback and MQTT history unchanged.
- The user's experimental home pilot authorizes exact `host_network`
  plus `NET_RAW` in version `0.1.11`, with negative policy tests. Continue
  to deny broader privileges; field validation of Ingress and ARP is pending. Do not claim Wi-Fi Engine operational.

## Wi-Fi positive-only pilot acceptance (0.1.14)

- CI verifies matching ARP MAC yields HOME and the existing MQTT Wi-Fi binary sensor becomes available; legacy GPS output remains unchanged.
- Test iPhone locked/asleep at home: repeated failed ARP replies must not cause NOT_HOME, `wifi_out`, `departure` or 'last resident left'. After 15 minutes the Wi-Fi source becomes unavailable only.
- Test a different MAC on a reused DHCP IP: discard Wi-Fi HOME proof immediately; never adopt the new phone. No raw IP/MAC in MQTT attributes.
- Test `wifi` mode starts unknown until MAC match then reports HOME; `hybrid` overrides old GPS away when Wi-Fi is freshly verified. GPS default remains unchanged.
- Field inspect the per-resident Wi-Fi binary sensor's `wifi_last_verified_at` and `wifi_probe_result` and the admin Ingress diagnostics; check private-MAC rotation and DHCP reassignment fail closed.
- Do not mark Wi-Fi absence or 15-minute departure accepted without independent, positive disconnect evidence.

## Wi-Fi notification acceptance (0.1.15)

- Observe an already connected phone at App startup: first positive ARP produces **no** artificial `wifi_in`.
- After 15 minutes with no matching MAC, expect exactly one `wifi_lost` event and a single `script.write2log` warning that Wi-Fi is **not confirmed**; no `wifi_out` or household departure.
- Return a matching-MAC ARP reply: expect one `wifi_in` and one `script.write2log` notification. Repeated subsequent probes do not notify again.
- Confirm MQTT Event includes `user_name`, `device_name` and `timeout_minutes` without exposing private IP/MAC.
- Confirm the package's root keys are valid for `packages: !include_dir_named packages`; do not add a duplicate name wrapper. Test on HAOS with iPhone sleep and actual Core Recorder configuration.
