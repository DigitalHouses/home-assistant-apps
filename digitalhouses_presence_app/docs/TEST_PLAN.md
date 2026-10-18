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

## Wi-Fi / hybrid field observation (0.1.17 — at least 3 days)

This pilot deliberately interprets completed local ARP misses as **network not
detected** after 15 consecutive minutes, including in hybrid mode. It is not
reliable proof of the iOS Wi-Fi toggle or association state. Do not authorize
alarm/shutdown/security decisions based on this pilot until observed and accepted.

- **On Wi-Fi, unlocked and sleeping:** log any false OFF or departure while
  resident remains home, including the exact time, `wifi_probe_result`, and
  timestamps in the Mushroom roster.
- **Wi-Fi deliberately switched off:** after 15 continuous minutes with valid
  `no_reply` probes, one Wi-Fi OFF and `wifi_out` event should occur. In
  `hybrid`, a HOME resident may also emit `departure` (last departure only
  if the whole household becomes NOT_HOME). No repeated notifications.
- **Wi-Fi switched on:** one matching MAC response should restore Wi-Fi HOME,
  `wifi_in`, and (if prior resident decision was away) `arrival`.
- **App restart:** a first successful HOME probe is a baseline, not a
  synthetic `wifi_in`; remembered resident decision timestamps must not be
  rewritten to the restart time. Initial unknown timestamps display `—`.
- **Failed probe:** disconnected network/route, execution permissions, missing
  tool or MAC mismatch yields Wi-Fi `unavailable` and resets the 15-minute
  negative streak; no fabricated `wifi_out` / `departure`.
- **Dashboard:** resident roster grows automatically with registered residents
  and displays local times for final/GPS/Wi-Fi changes. No IP/MAC leakage.
- **Notifications:** one `script.write2log` per emitted machine event; local
  `!include_dir_merge_named` package has only one automation and accurately
  labels Wi-Fi OFF as ARP nonresponse, not verified radio disconnection.

Observe at least 3 days of normal iOS sleep/wake, Wi-Fi off/on, and changing
GPS reports; any false departure while actually at home must be treated as a
failed pilot acceptance requiring adjustment or reversion to GPS mode.

## Event-history display regression (0.1.28)

1. Install App with `events_history_limit: 5`. Confirm discovery of diagnostic `sensor.dh_presence_app_recent_events` in the existing MQTT device, with `count=0` on a new install and no fabricated event on startup.
2. Cause more than five real GPS/Wi-Fi/zone machine Events. Verify only the five latest **acknowledged publications** remain, newest first. The Markdown UI must not subscribe to MQTT, persist data, or maintain template-sensor state itself.
3. Restart App and MQTT broker; verify the same retained bounded list returns without re-emitting transient MQTT Events or writing additional log messages.
4. Change Configuration to `events_history_limit: 2`, restart; verify persisted cache and MQTT snapshot trim to two. Invalid values outside 1–20 must fail App option validation.
5. Exclude an administrator's verified HA User ID; verify no admin zone/source event is produced and previously cached rows for removed users are purged.
6. Verify persisted ring and MQTT attributes do not include registration IP/MAC, tokens or credentials. Private IP/MAC remain visible only in the admin-only Ingress diagnostics card.
7. Inspect Recorder exclusions: `sensor.dh_presence_app_recent_events` must be explicitly excluded, so every display update does not add a new Recorder row with array attributes. The existing machine-event entity's Recorder policy is unchanged.
8. Disconnect MQTT while a local transition occurs. Events not actually published must not enter the App's published-events history or be reconstructed as false notifications.

## Phone administration acceptance (0.1.29)

1. Enrol a phone, verify it appears in the registered-phone Markdown card and in the authenticated admin Ingress list. Legacy-only unverified trackers must not appear in the registered list.
2. On an ordinary resident account, the admin management launcher is hidden and the backend rejects direct delete requests. Verify missing action header, malformed payload and unavailable HA admin verification all fail without registry writes.
3. Authenticate an administrator through local HA and through an already-authorized Cloudflare connection; open the private phone list with enrollment IP/MAC, select the exact phone and confirm deletion. No LAN ARP step is required to delete.
4. Verify the phone's MQTT source entities are retired via Discovery cleanup, the aggregate resident list updates and no departure/zone event or notification is fabricated.
5. Keep the deleted phone listed in legacy App Configuration `residents`, restart: the phone stays deleted and untracked because the existing v2 private registry retained its disabled tracker ID.
6. Re-enrol the physical phone through local Home Assistant with a fresh MAC observation; verify disabled state is cleared and GPS/Wi-Fi presence starts with unknown baseline, not synthetic arrival.
7. Verify old v1 registration state migrates safely on write, malformed v2 tombstones fail explicitly, and no IP/MAC/secret is introduced to public MQTT or Recorder.

## Private IP/MAC phone tree acceptance (0.1.30)

1. Open **Open Web UI** with verified HA administrator identity: observe the compact registered-phone tree containing five lines per phone (device, GPS, Wi-Fi, IP at registration, MAC at registration), plus one root line. Two phones have correct `├─ / └─` ancestry, no extra line spacing.
2. Verify the IP and MAC are saved enrollment snapshots, not presented as current online values. They must be exactly those in the App's existing registry (no probes on rendering).
3. Open as a normal HA user or make the admin role verification unavailable: backend denies access, private tree remains hidden, and failure clears any previously rendered IP/MAC values.
4. Confirm the public Lovelace registered-phone card, `residents_home` attributes, MQTT topics, Event and Recorder still contain **no** registration IP or MAC.
5. Delete one registration via the existing admin action: refresh removes that phone and its private network details from the tree, with no false departure Event. Verify real re-registration adds it back.


## HA Lovelace registered phones with IP/MAC (0.1.31)

1. Upgrade App to 0.1.31 and replace the *existing manually installed*
   registered-phones Markdown YAML with the new version from this repository.
   Verify the normal HA dashboard tree shows both `IP (рег.)` and
   `MAC (рег.)` beneath each phone, along with GPS and Wi-Fi.
2. Verify the App's single new
   `sensor.dh_presence_app_registered_phones` diagnostic has numeric state
   and a multiline `tree` attribute; no markup reconstruction is done by HA.
3. Verify IP/MAC in this sensor equal the registration snapshots, not current
   network attachment. Confirm no repeated retained tree publications when
   GPS polls but no registration details change.
4. Delete a phone in Ingress, keep it in legacy `residents` config, restart:
   the new retained tree excludes the deleted phone's IP/MAC and it cannot be
   re-enrolled silently. Administrators excluded from tracking do not appear.
5. Confirm the ordinary `residents_home` state attributes and Event payloads
   still contain no enrollment IP/MAC.
6. Merge new `sensor.dh_presence_app_registered_phones` entity into the home's
   existing Recorder exclusion alongside
   `sensor.dh_presence_app_recent_events`; confirm database does not record
   the new `tree` attributes.
7. Verify access classification explicitly: MQTT subscribers and HA users
   with state access can read network details. Private Ingress remains the
   stronger choice for administrators-only data.

## MQTT select/button phone removal acceptance (0.1.33)

1. Upgrade to 0.1.33. Verify the DH Presence MQTT Device contains
   `select.dh_presence_app_remove_phone` and
   `button.dh_presence_app_delete_registration`, with the App-generated
   options `— Выберите телефон —`, `Имя (устройство) · device_tracker`.
   On restart the select must reset to the placeholder.
2. Paste the standalone admin-only card, or refresh the maintained
   dashboard YAML. Only HA frontend admins should *see* the control; no
   `custom:addon-iframe-card` or HACS installation is needed.
3. Select one of two real phones, press the button, confirm the Lovelace
   prompt, and check the App has deleted exactly that phone, cleared the
   selection, updated available options and removed the tree branch.
   Verify no synthetic departure/zone_leave events, and durable tombstone
   blocks the old config residents list from resurrecting the phone.
4. Press delete without selection; replay a retained select, retained DELETE,
   unknown choice and duplicate non-retained DELETE after success: all must
   be no-ops. A concurrently deleted selection must be refused.
5. Verify the surviving phone is unchanged and can still be selected/deleted
   separately; ensure a phone excluded by user ID cannot appear in choices.
6. Confirm both MQTT and native Ingress deletion coordinate their writes
   with the same lock, preserving atomic registry state.
7. Review security: hiding in Lovelace is not MQTT ACL or HA admin
   authorization. Use real Ingress admin auth if that guarantee is required.
   Recorder exclusions for recent-events and registered-phones tree are
   unchanged, with no new data-recording entity or App privileges.

## Live GPS/Wi-Fi source status phone tree (0.1.34)

1. Upgrade App to 0.1.34 without editing the existing Lovelace Markdown tree.
   For a registered phone, verify the first branch icon is 📲 rather than 📱.
2. At home with confirmed Companion GPS `home` and router Wi-Fi
   `home`, expect both branches to show `🟢 Дома`, each with its tracker ID.
3. Simulate a genuine `not_home` observation from either source: only that
   source's branch becomes `🟠 Не дома`, irrespective of gps/wifi/hybrid
   mode. Registration data and entity ID do not change.
4. When GPS is unavailable/stale or router API unavailable, the corresponding
   source must show `⚪ Недоступно`, **not** false `🟠 Не дома`.
   Missing Wi-Fi tracker shows `⚪ Не привязан`.
5. Observe the same `sensor.dh_presence_app_registered_phones` tree attribute
   update on the next App snapshot while `count` is unchanged. Verify no
   new MQTT entity, Recorder metric or fake arrival/departure event is created.
6. Keep the diagnostic sensor excluded from Recorder; it now changes on
   source-status transitions in addition to registrations.

## Current GPS/Wi-Fi status timestamp tree (0.1.35)

1. Update DH Presence App to 0.1.35; keep the existing tree Markdown YAML.
   For each registered phone, expect GPS and Wi-Fi state rows each followed
   by an indented `└─ Статус с · dd.mm.yyyy hh:mm TZ` child line.
   Both source rows still carry the original tracker name and emoji.
2. In a home configured with `time_zone: Asia/Almaty`, verify UTC
   source status timestamps convert to UTC+05:00. If HA timezone fails,
   the fallback is explicitly marked UTC, not an invented local time.
3. Repeated identical GPS or router Wi-Fi polls must **not** alter the
   source status-since timestamp or publish an changed retained tree.
   A genuine independent source state change must update only the
   matching source timestamp in the next App MQTT snapshot.
4. A temporarily unavailable GPS or router must show `⚪ Недоступно`
   with the transition's own time, not the timestamp of the previous
   `Дома` state. No fake `gps_out`, arrival or departure Events.
5. Before first source evidence, show `нет данных`. For an unlinked
   router Wi-Fi tracker, show `не применимо` instead of a fictional
   transition. After App restart initial source transition timestamps
   come from fresh source observation/first status evaluation; do not
   claim restored time that was never persisted.
6. Verify the same existing MQTT entity/tree and compact PVE-style
   `line-height:1` card, IP/MAC privacy contract and Recorder exclusion.

## HA local wall-time only in phone tree (0.1.36)

1. Upgrade App to 0.1.36, preserve the existing dashboard YAML.
   With HA `time_zone: Asia/Almaty`, source event
   `2026-10-18T20:12:00+00:00` must display
   `Статус с · 19.10.2026 01:12`, **without** `+05` or `UTC`.
2. For a DST-observing HA timezone, verify actual local hour adjustment
   in January vs July, with no timezone suffix on either timestamp.
3. When HA Core timezone is missing/invalid, **do not substitute**
   unlabeled UTC: display `местное время недоступно`; retry config
   periodically and restore local formatting once it becomes valid.
4. Distinguish missing observation timestamp (`нет данных`) and
   unlinked router Wi-Fi (`не применимо`). All source status and
   last-transition semantics remain unchanged. No HA templates, MQTT
   entities or Recorder writes are added.
