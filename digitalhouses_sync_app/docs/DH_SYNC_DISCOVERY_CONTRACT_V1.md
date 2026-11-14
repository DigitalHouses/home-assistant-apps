# DH Sync Discovery Contract v1 — DigitalHouses owner only

## Source admission

**The only admission rule is: the GitHub repository owner is DigitalHouses.** Any GitHub repository under that organization is accepted. There is no repository allowlist, no specific product registry gate, no static product commit mapping and no required Agent/App compatibility range for read-only discovery.

A repository URL must still be a structurally valid direct HTTPS GitHub URL, e.g. https://github.com/DigitalHouses/home-assistant-apps or https://github.com/DigitalHouses/recorder. This avoids accidentally fetching an unrelated host. Arbitrary URLs from MQTT are never passed directly to a network fetcher.

## MQTT metadata

Existing producers continue to publish retained QoS 1 /sync metadata on each connect/reconnect:

- DigitalHouses/Global/<product_id>/sync (single instance)
- DigitalHouses/Global/<product_id>/<instance_id>/sync (multi instance)

Typical JSON:

```json
{"schema":1,"product_id":"digitalhouses_recorder_app","type":"app","version":"0.1.28","repository":"https://github.com/DigitalHouses/home-assistant-apps","product_path":"digitalhouses_recorder_app"}
```

The topic is the source of product identity; repository is required for admission. Fields such as schema, type, version and product_path are informational, not approval gates. A malformed relative product_path falls back to the topic product ID. A dedicated repository may use product_path '.'.

Retained /sync does not prove online availability or uninstall. Availability remains in its existing product topic. No heartbeat is added.

## Dynamic dashboards

On an explicit user action, DH Sync resolves the owned repository's default branch to one Git SHA and reads its dashboards/ru/*.yaml at that revision. DH-View-Version and DH-Compatible-Agent/App headers are optional informational values, not prerequisites for displaying a view. No product has to be manually registered in DH Sync.

Basic transport/path safety and standalone YAML parsing remain to keep requests and the read-only view meaningful. The current App never changes HA configuration. Being owned by DigitalHouses does not authorize automatic installation; backup, visible review and user approval are separate future work.
