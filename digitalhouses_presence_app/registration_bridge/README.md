# DH Presence · authenticated Companion registration bridge

This **minimal Home Assistant Core integration** is the security boundary for
one-time phone enrollment. A Supervisor Home Assistant App cannot access
`ActiveConnection.user` or the actual WebSocket peer address on its own.
The existing DH Presence App remains the sole presence/GPS/MQTT engine.

## One-time installation on a house (NOT per resident)

1. Put `registration_bridge/custom_components/dh_presence_registration/`
   (both `__init__.py` and `manifest.json`) under
   `/config/custom_components/dh_presence_registration/` in Home Assistant.
   Do **not** put the bridge files inside the App's `/data`.
2. Add this **single integration key** to `/config/configuration.yaml`:
   ```yaml
   dh_presence_registration:
   ```
3. Copy `registration_bridge/www/dh-presence-register-card.js` to
   `/config/www/dh-presence-register-card.js`.
4. Restart Home Assistant **Core** once via Settings. Do not restart PVE.
5. In the dashboard Resources, add the JS **module** resource URL
   `/local/dh-presence-register-card.js`.
6. Install/update the DH Presence App to version 0.1.11 (GPS data and existing
   confirmed states remain intact; back up the App beforehand). The managed
   Lovelace DH Presence card includes `custom:dh-presence-register-card`.

These are **one-time deployment prerequisites for the house**. Enrolling each
resident/phone afterwards requires no YAML, manual name, HA user ID, IP or MAC.

## Register a resident phone

1. Open the HA Companion app on the **specific** phone, connected over the
   real home Wi-Fi and **Internal URL** (not mTLS Cloudflare/Tailscale/VPN).
2. Open the DH Presence dashboard, find the "Регистрация телефона" control.
3. Select the desired registered **Mobile Companion device** with a GPS
   tracker. A second phone/iPad using the same HA account is **not selected
   automatically**.
4. Tap "Зарегистрировать" and confirm that this is the physical device in
   hand. The bridge reads the authenticated HA WebSocket `connection.user`
   and `connection.remote`. The browser does not submit trusted user name,
   user ID, IP or MAC. A short-lived pending request is stored in HA.
5. The Presence App (using its existing authenticated Core API) fetches the
   pending request. It checks a **directly connected LAN route**, selects the
   real outbound LAN interface, issues a fresh **active ARP** request and
   accepts only one unambiguous MAC reply from the request IP. Stale neighbour
   cache results and failed pings never produce registration.
6. The App atomically persists `user_id, user_name, device_name, device_id,
   entry_id, tracker, ip, mac` under its own `/data/presence_registrations.json`
   (mode 0600), enrolls the GPS tracker, republishes MQTT Discovery and
   acknowledges success to the bridge. User name/device name then appear as
   `Имя жильца (Устройство)` in the roster automatically.
7. Tap "Обновить список" to see a confirmed `registered` outcome and MAC,
   not merely `pending_arp_verification`.

The App's configuration `residents` and `resident_names` lists are
**legacy compatibility inputs** only; they are not a new registration step.
A blank `residents: []` is valid once the bridge is active.

## Security and acceptance limitations

- Missing bridge or API authorization, no direct LAN route, ARP timeout,
  multiple MAC replies, invalid GPS tracker or account mismatch all **fail
  closed**. GPS observation of previously registered residents still runs.
- `exclude_users` is a list of HA user IDs controlled by the administrator.
  Those users are ignored by the App during enrollment and counting.
- HA Core knows the authenticated WebSocket user, not the physical identity of
  the selected Companion device. Choosing the phone is explicit and must be
  confirmed by the resident. A user with two Companion devices can pick the
  wrong one; cross-device cryptographic attestation is **not yet proven**.
  Do **not** connect this pilot to an alarm.
- On LANs with a reverse proxy on the same subnet, a private peer address plus
  ARP alone cannot prove physical device identity. The existing single-user
  laboratory test established the chain, but production still needs an
  independently attested local device/IP association.
- iOS private Wi-Fi MAC can rotate, and DHCP IP may change. Registration
  records a verified point-in-time binding only. Future Wi-Fi Engine must
  handle rotation/reverification; it must not treat isolated ARP misses as
  departures. **No Wi-Fi absence detector is enabled by this bridge.**
- The App gets `host_network` + `NET_RAW` specifically for L2 ARP (not
  `NET_ADMIN`, host PID, privileged Docker API, or writable HA config).
  This host networking change requires a scoped home-pilot acceptance.
- Private identities are stored in HA `.storage` for pending requests and
  in the App `/data` for accepted bindings, not in analytics or telemetry.
  MAC/IP are not added to the public MQTT resident attributes.
- The native Supervisor's Core API proxy must permit the App to read and
  acknowledge a pending request as the privileged internal principal.
  If HTTP 403 occurs, treat it as a hard blocker; do not bypass authentication.

## Troubleshooting

- `unknown_command`: bridge integration was not loaded; check
  `configuration.yaml` and Core logs.
- `not_allowed`: remote peer is not a local candidate or selected device
  is not registered to the logged-in HA user.
- `pending_arp_verification`: WebSocket phase passed; verify the App's host
  networking, ARP permission and actual on-link reachability. Do not manually
  enter an IP/MAC to bypass the gate.
- `403` on bridge pending API: Supervisor-auth bridging needs verification on
  the target HAOS version. The App must not self-register using MQTT instead.
- `Wi-Fi home unavailable`: expected until the separate verified Wi-Fi
  presence engine is accepted.
