# DH Sync v1 — DigitalHouses Plex Agent canonical YAML contract

Status: product-team Draft PR. HOME baseline and agent v0.8.17 verified; DH Sync delivery/adoption is NOT yet approved.

## Identity and runtime

- Canonical product ID: `digitalhouses_plex_agent` (`linux_agent`; unchanged).
- Original YAML source was captured on v0.8.16; HOME has since been upgraded to released v0.8.17. The narrowly tested agent revision is >=0.8.17,<0.8.18. Do not extend the range automatically to future versions.
- Existing product-level MQTT availability (default `instance_id=plex`): `DigitalHouses/Global/digitalhouses_plex_agent/availability`. A non-default `instance_id` uses its existing instance-specific suffix. Do not rename either namespace.
- Product availability sends retained `online` on MQTT connection; retained LWT sends `offline`. The current Plex LWT uses QoS 0. Existing reconnect, `MQTT_PAUSED` and optional collector/Plex API availability are not product uninstall signals.
- MQTT Device Discovery uses the existing `homeassistant/device/<device_id>/config` pattern with retained QoS 1 / PUBACK reconciliation. Discovery is repaired on HA birth, reconnect and periodic recheck. The device identifier and MQTT base remain unchanged.
- Version entity: `sensor.dh_plex_agent_version`; source: the running release build info in the existing state payload. Started-at entity: `sensor.dh_plex_agent_started_at` (timestamp). No new health heartbeat required.
- There is no new machine-readable uninstall tombstone in this PR. DH Sync must retain a known product on `offline` and require confirmed removal before deleting its own resources.

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

- Product compatibility now explicitly covers ONLY agent >=0.8.17,<0.8.18, based on HOME. This version selector is NOT authorization to write to HA: Storage adoption, backups, rollback, config validation and explicit operator consent remain separate mandatory DH Sync gates.
- EN locale is missing; only the real Russian/operator-approved dashboard is shipped.
- No live two-HA DH Sync adoption, update, rollback, restart-required flow or missing-HACS-dependency acceptance has been performed. CORE runtime is unverified for this candidate.
- Live HOME MQTT CONNECTED is confirmed; broker-retain inspection, forced LWT/reconnect, custom instance IDs and uninstall semantics remain to be tested.
- No canonical localized notification package is proposed; audit of deployed local notification rules is a separate task.

## Validation

Run `PYTHONPATH=digitalhouses_plex_agent python -m pytest digitalhouses_plex_agent/tests -q` and `python scripts/validate_repository.py` in repository CI. `tests/test_dh_sync_canonical_resources.py` validates comment headers, exactly preserved YAML bodies, baseline identifiers and Recorder membership. Repository YAML parsing/contract CI is separate. Do not deploy, merge or modify other products through this PR.
