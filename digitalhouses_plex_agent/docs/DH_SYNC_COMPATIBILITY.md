# DH Sync v1 — DigitalHouses Plex Agent canonical YAML contract

Status: product-owned compatibility review candidate. HOME v0.8.17 baseline verified; v0.8.18 source delta reviewed, but live v0.8.18 dashboard acceptance and DH Sync YAML adoption are NOT yet approved.

## Identity and runtime

- Canonical product ID: `digitalhouses_plex_agent` (`linux_agent`; unchanged).
- Original YAML source was captured on v0.8.16; HOME has since been upgraded to released v0.8.17. The narrowly source-reviewed compatibility range is >=0.8.17,<0.8.19 after inspecting v0.8.18 PR #504. The live dashboard baseline is only v0.8.17; do not extend this range to future releases without review.
- Existing product-level MQTT availability (default `instance_id=plex`): `DigitalHouses/Global/digitalhouses_plex_agent/availability`. A non-default `instance_id` uses its existing instance-specific suffix. Do not rename either namespace.
- Product availability sends retained `online` on MQTT connection; retained LWT sends `offline`. The current Plex LWT uses QoS 0. Existing reconnect, `MQTT_PAUSED` and optional collector/Plex API availability are not product uninstall signals.
- MQTT Device Discovery uses the existing `homeassistant/device/<device_id>/config` pattern with retained QoS 1 / PUBACK reconciliation. Discovery is repaired on HA birth, reconnect and periodic recheck. The device identifier and MQTT base remain unchanged.
- Version entity: `sensor.dh_plex_agent_version`; source: the running release build info in the existing state payload. Started-at entity: `sensor.dh_plex_agent_started_at` (timestamp). No new health heartbeat required.
- There is no new machine-readable uninstall tombstone in this PR. DH Sync must retain a known product on `offline` and require confirmed removal before deleting its own resources.

## DH Sync Discovery Contract v1 — product source MQTT

Plex Agent 0.8.18 uses the existing Paho MQTT client to publish the
new metadata topic on successful connect and on every reconnect:

- Standard instance (instance_id=plex):
  DigitalHouses/Global/digitalhouses_plex_agent/sync
- Additional instance (for example plex_guest):
  DigitalHouses/Global/digitalhouses_plex_agent/plex_guest/sync

The topic is derived from the canonical product registry identity and
stable instance ID, NOT the configurable legacy mqtt.topic_prefix.

Exact JSON fields for the default instance (the shown version is only an
example; the runtime uses BuildInfo.version, validated against VERSION):

    {"schema":1,"product_id":"digitalhouses_plex_agent",
     "type":"agent","version":"0.8.17",
     "repository":"https://github.com/DigitalHouses/home-assistant-apps",
     "product_path":"digitalhouses_plex_agent"}

Paho publishes with QoS 1, retain=true through the existing connection,
without an extra heartbeat, process, thread, retry policy, credentials
or private-site details. It does not block the Paho network callback
waiting for PUBACK. This process's build/version is immutable: when an
updated agent starts, it connects again and announces the new version.

Existing product-level availability, retained offline LWT, Discovery
device/unique/entity IDs, Version/Started-at sensors, and MQTT_PAUSED
fail-safe behavior remain unchanged. A retained /sync topic is only
MQTT-claimed source metadata: it never authorizes installation or
uninstallation. DH Sync validates DigitalHouses owner, immutable Git
resource revisions, compatibility, backup and operator approval separately.

Plex Agent 0.8.18 publishes this metadata only after the service is
updated and restarted. The previously verified HOME installation ran
0.8.17 and does not yet publish /sync. The canonical dashboard/package compatibility range is proposed as >=0.8.17,<0.8.19 by this PR after source review. Live v0.8.18 dashboard verification is still required before merging; DH Sync auto-apply remains separately gated.
No current Home Assistant YAML has been changed by the agent release.

## 0.8.18 compatibility evidence and remaining gate

Merged release PR #504 changes the existing MQTT bridge to additionally publish retained
QoS 1 /sync metadata on connect/reconnect. In app/app.py it passes sync_payload
to the existing bridge. In discovery.py the existing device_id is still the
same string, now composed from SYNC_PRODUCT_ID, and the old telemetry topic
prefix and existing Home Assistant entities are preserved. No dashboard cards,
legacy entity IDs, source telemetry or Recorder membership changed in 0.8.18.

The canonical view and Recorder package have **only their compatible-agent comment
header changed** to >=0.8.17,<0.8.19. View/package revisions remain 1.0.0, and
product regression tests still compare the complete bodies byte-for-byte to
the approved sources and assert the original 24 included / 6 excluded entities.
CORE live MQTT showed 0.8.18 Online; it does NOT confirm card rendering.

This is a **Draft compatibility review**. Before it may merge, the product owner
must confirm the Plex view renders on 0.8.18. This does not authorize automatic
Storage migration, a new dashboard sidebar, package installation or any HA writes.

## Canonical resources

| Resource | Path | Revision | Source |
| --- | --- | --- | --- |
| Russian view | `dashboards/ru/10_plex.yaml` | `DH-View-Version: 1.0.0` | Approved deployed dashboard from PR #493, stored at `examples/lovelace/plex-dashboard.yaml` |
| Common Recorder package | `packages/common/dh_plex_app_package.yaml` | `DH-Package-Version: 1.0.0` | Operator-supplied current package, identical to `examples/packages/dh_plex_app_package.yaml` (Git blob `72cf231da4e9e1c7a28fa7452b50c58f811dc6b0`) |

Only comment headers were added. Tests compare the remaining bytes with the existing examples. Agent `VERSION` stays independent of view/package revisions.

The published binary release tag digitalhouses_plex_agent-v0.8.17
predates these canonical YAML files and cannot be used as the YAML source.
After merging this PR, DH Sync must pin the immutable merged commit SHA
(or a later verified resource tag). Never equate the agent tag with a
Git revision containing the canonical YAML merely because versions match.


### View

- `type: sections`, `title: Plex`, `path: dh-plex-agent`. Treat as **one view** for the unified DigitalHouses dashboard; do not register a new sidebar or wrap it in `lovelace:`.
- Existing four sections, entity IDs, card actions, charts, server identity, GPU and dynamic media/storage cards remain unchanged.
- Frontend dependencies from the approved YAML: HACS/custom `mushroom-template-card`, `mushroom-chips-card`, `auto-entities`, `button-card`, `entity-progress-card-template`. DH Sync must inform the user if any are missing; it must not install HACS itself.
- Missing data or offline agents do not authorize removing this view. The original design uses existing conditional and availability logic; live UI behavior still requires HA acceptance.
- English locale `dashboards/en/` is **not available**: translation requires design review of all embedded Russian, English and Jinja UI strings. No synthetic English file is supplied.

### Recorder package

- Keep package filename `dh_plex_app_package.yaml` and historical top-level key **`dh_app_plex_monitoring_package`** to preserve deployed configuration semantics.
- Keep exactly the same 24 included and 6 excluded Recorder entity IDs. GPU diagnostic event/verbose session sensors remain excluded, not relabeled.
- Do **not** install alongside `examples/packages/dh_plex_agent_recorder_package.yaml`: the two variants overlap in Recorder configuration. The canonical copy is a managed replacement of the already deployed package, not an additional package.
- The canonical copy does not contain site-specific notify targets, credentials, IPs, or a new notification automation. Existing GPU machine events and local notification policy remain untouched.
- Do not assume a package can be hot-reloaded. The operator should validate HA configuration and follow the site's established restart procedure when applying a Recorder package.

## Verified HOME baseline (operator-provided checks, 2026-11-14)

- Installed Recorder path: /config/packages/DH/dh_plex_app_package.yaml.
  Original installed file SHA-256:
  340cce8e68477b2faf2192f50465471e18c7e9311b46930620a4c01b7e62ff4a.
  This SHA is for the installed file, NOT the metadata-bearing canonical
  Git file. Compare semantic Recorder content, then verify metadata separately.
- The Plex view lives inside the existing multi-view Storage dashboard
  /config/.storage/lovelace.dashboard_system, view index 13, path dh-plex-agent,
  title Plex, type sections, with four sections. The user compared the
  complete Storage view against normalized canonical YAML; identical
  normalized JSON SHA-256:
  9a1f922f58bcdcc2fc285c9f262f57ab9aed22a3487899d8cf64fe2d5bbb48b8.
  No content discrepancy was detected at the baseline check.
- After agent upgrade to v0.8.17 (commit d38bf94542544d0e54dfff5c9431241e369566cf)
  the active Linux service reported MQTT CONNECTED, QoS1 PUBACK received,
  Plex API ok, Agent CPU around 1%, overload OFF, and CLI update returned
  UP_TO_DATE 0.8.17. The existing dashboard content was not changed by
  this runtime release. The current YAML selection is intentionally exact
  to this minor patch release; no broader compatibility is asserted.
- This establishes narrow product-source compatibility on HOME. It does not
  establish end-to-end DH Sync migration, cross-HA acceptance, or the
  appearance of every conditional UI card following the agent update.
- New v0.8.17 CPU self-diagnostic entities do not require changes to the
  existing canonical dashboard. The verified Recorder package is preserved
  unchanged (24 include / 6 exclude); optional CPU history is a future
  reviewed package revision, not a silent change.

## Adopting an existing HA installation

1. Compare actual Storage view and installed package as parsed YAML/JSON (ignore only metadata comments and nonsemantic whitespace); preserve local differences and stop if mismatched.
2. Back up resources before explicit operator-approved adoption. The live view belongs to Storage dashboard_system: DO NOT edit .storage directly, delete or replace the dashboard, or create a duplicate dh-plex-agent path. If a supported, reversible Storage-to-YAML migration is not implemented in DH Sync, make NO writes.
3. Ensure there is only one active Recorder package for this Plex agent and retain the exact top-level key.
4. Validate Home Assistant YAML and required frontend resources; only then enable managed updates. Removing the app/agent or losing MQTT must not silently remove user-managed resources.
5. Deletion from DH Sync, when explicitly confirmed, must remove only its managed files with backup/rollback support.

## Open acceptance gaps

- Product source compatibility candidate covers ONLY agent >=0.8.17,<0.8.19 (v0.8.17 HOME live baseline; v0.8.18 release source delta only, no live dashboard verification). This version selector is NOT authorization to write to HA: Storage adoption, backups, rollback, config validation and explicit operator consent remain separate mandatory DH Sync gates.
- EN locale is missing; only the real Russian/operator-approved dashboard is shipped.
- No live two-HA DH Sync adoption, update, rollback, restart-required flow or missing-HACS-dependency acceptance has been performed. CORE runtime is unverified for this candidate.
- Live HOME MQTT CONNECTED is confirmed; broker-retain inspection, forced LWT/reconnect, custom instance IDs and uninstall semantics remain to be tested.
- No canonical localized notification package is proposed; audit of deployed local notification rules is a separate task.

## Validation

Run `PYTHONPATH=digitalhouses_plex_agent python -m pytest digitalhouses_plex_agent/tests -q` and `python scripts/validate_repository.py` in repository CI. `tests/test_dh_sync_canonical_resources.py` validates comment headers, exactly preserved YAML bodies, baseline identifiers and Recorder membership. Repository YAML parsing/contract CI is separate. Do not deploy, merge or modify other products through this PR.
