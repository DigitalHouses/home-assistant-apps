# DH Sync v1 — DigitalHouses Plex Agent canonical YAML contract

Status: product-team draft for review; **not** a production compatibility approval.

## Identity and runtime

- Canonical product ID: `digitalhouses_plex_agent` (`linux_agent`; unchanged).
- Source agent release observed for this baseline: `0.8.16` on `main` at the time the YAML was copied. This is **not** a validated version range.
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

## Adopting an existing HA installation

1. Compare the actual installed dashboard and package against the canonical body, **ignoring only DH metadata comments**. Preserve any local changes and stop if there are unexpected differences.
2. Back up existing resources. Configure DH Sync to adopt their current paths/identities before switching ownership; never silently replace an unknown user file.
3. Ensure there is only one active Recorder package for this Plex agent and retain the exact top-level key.
4. Validate Home Assistant YAML and required frontend resources; only then enable managed updates. Removing the app/agent or losing MQTT must not silently remove user-managed resources.
5. Deletion from DH Sync, when explicitly confirmed, must remove only its managed files with backup/rollback support.

## Open acceptance gaps

- **No `DH-Compatible-Agent` header yet**: live validation of the complete view/package on actual agent revisions is pending; automatic YAML application must remain blocked until a proven range is approved.
- EN locale is missing; only the real Russian/operator-approved dashboard is shipped.
- No live two-HA DH Sync adoption, update, rollback, restart-required flow or missing-dependency acceptance has been performed.
- Product-level MQTT behavior is source-audited, but retained broker state, LWT/reconnect, custom instance IDs and uninstall semantics need live acceptance.
- No canonical localized notification package is proposed; audit of deployed local notification rules is a separate task.

## Validation

Run `PYTHONPATH=digitalhouses_plex_agent python -m pytest digitalhouses_plex_agent/tests -q` and `python scripts/validate_repository.py` in repository CI. `tests/test_dh_sync_canonical_resources.py` validates comment headers, exactly preserved YAML bodies, baseline identifiers and Recorder membership. Repository YAML parsing/contract CI is separate. Do not deploy, merge or modify other products through this PR.
