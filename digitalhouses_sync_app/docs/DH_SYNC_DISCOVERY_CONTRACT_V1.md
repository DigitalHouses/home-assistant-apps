# DH Sync Discovery Contract v1 — MQTT product source

**Status:** accepted interface for new DigitalHouses Agent/App releases.
Pilot DH Sync v0.1.0 accepts and displays metadata but does not yet use
MQTT-supplied repositories for YAML installation.

## Purpose

Every DigitalHouses product publishes its identity, release version and the
GitHub repository that owns its canonical YAML. DH Sync can discover products
without keeping a continually updated mapping of product to repository.

The message describes a *claimed source*. **It is not authorization to
download or install executable code, dashboards or packages.**

## MQTT topic

Keep every existing MQTT availability and Home Assistant Discovery topic.

Publish the new **retained QoS 1** message when MQTT connects, reconnects or
the fields change. No new heartbeat.

- Single/default instance:
  `DigitalHouses/Global/<product_id>/sync`
- Multi-instance product:
  `DigitalHouses/Global/<product_id>/<instance_id>/sync`

`product_id` is canonical from `product_registry.json`, not a friendly
name. Use the existing stable instance ID when one is already part of the
product's MQTT namespace. The presence of a retained metadata topic, or the
loss of an online availability message, does **not** prove installation or
uninstallation; keep product-level availability separate.

## Payload

```json
{
  "schema": 1,
  "product_id": "digitalhouses_pve_agent",
  "type": "agent",
  "version": "0.5.88",
  "repository": "https://github.com/DigitalHouses/home-assistant-apps",
  "product_path": "digitalhouses_pve_agent"
}
```

| Field | Rule |
| --- | --- |
| `schema` | Integer 1, not boolean |
| `product_id` | `digitalhouses_<name>_agent` or `digitalhouses_<name>_app`; must match topic |
| `type` | Exactly `agent` or `app`, consistent with the ID |
| `version` | Installed running release, SemVer |
| `repository` | Direct HTTPS GitHub repository under exact `DigitalHouses` owner |
| `product_path` | Canonical product directory in monorepo; `.` for a dedicated repository |

The repository URL identifies *where* the product is maintained, not the
revision of its canonical YAML. View revisions and Agent/App releases are
separate. Do **not** announce an unverified Git revision via MQTT as an
authoritative update.

## Exact GitHub owner restriction

Accept only:
```text
https://github.com/DigitalHouses/home-assistant-apps
https://github.com/DigitalHouses/another-agent
```

Validation must parse the URL structurally and normalize owner case.
Reject HTTP, any domain other than exact `github.com`, userinfo, ports,
query strings, fragments, extra URL path segments, encodings (`%`),
backslashes, non-ASCII hostnames, whitespace, `.` / `..` names, and
path traversal.

Reject, for example:
```text
https://github.com/OtherUser/repo
https://github.com/DigitalHouses-malicious/repo
https://github.com/DigitalHouses/repo/../../OtherUser/repo
https://github.com@evil.example/repo
https://github.com.evil.example/DigitalHouses/repo
http://github.com/DigitalHouses/repo
```

**Do not fetch arbitrary URLs from MQTT.** URL parsing does not prevent
redirects if a future downloader follows them; any downloader must use a
GitHub-only API transport, reject off-domain redirects, verify the final repo
owner and pin an immutable reviewed Git commit. Validate resource paths,
headers, compatibility, hashes, existing installation, backups and local
modifications before *manual* approval.

A compromised MQTT broker can lie about a product and even about a valid
DigitalHouses repository. Organizational ownership is a useful restriction,
**not** cryptographic authentication of an agent or security certification
of a specific file in the repository.

## DH Sync v0.1 behavior

- Subscribes to both sync topic depths and validates exact topic-to-payload
  identity, schema and repository owner.
- Saves only accepted canonical metadata in
  `/data/product_sources.json`, and displays it as *MQTT claimed metadata*.
- Ignores/rejects malformed metadata. Offline doesn't purge last known
  sources. No product removal based on absence of metadata.
- Maintains the existing legacy availability inventory for producers that
  have not implemented this contract.
- The **Apply controller is unchanged**: only the three previously pinned
  Proxmox/UPS/Plex resources are allowed; MQTT metadata has no influence
  on the download endpoint, source commit or destination path.

## Product-team acceptance

Each product's own PR adds retained publication and tests of the new topic,
without changing existing availability, MQTT Discovery, entity IDs,
credentials, or update services. The product team reports its actual topic
and demonstrates publication on normal MQTT reconnect. First pilot:
PVE Agent and Plex Agent, then HAOS Apps.
