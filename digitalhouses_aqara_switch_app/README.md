# DigitalHouses Aqara Switch App

**Status: experimental, inert scaffold — not a functional release.** The source directory exists to establish the canonical product and its architecture. It currently does not scan Zigbee2MQTT, handle MQTT actions, write device modes, or control Home Assistant. Keep legacy AQPM2 operational until the separately tested cutover.

## Purpose and scope

Declarative mapping of **physical Aqara button/key actions to HA targets**, supporting wired switches, battery buttons, wireless keypads and panels. Supported targets will include lighting, groups, covers, switches, scenes and HA scripts. Compatible wired devices will additionally support Mode Keeper and a controlled Maintenance Mode for pairing/servicing. This is **not** a general automation engine or Zigbee network monitor.

## Requirements agreed for implementation

- **Scan** is launched only by an explicit user action from the HA UI. No startup scan, background scan or periodic scan.
- The authoritative device inventory, capabilities and actual device settings come from **Zigbee2MQTT MQTT**.
- Rooms come from **Home Assistant Area Registry**, resolved through its Device Registry, not guessed from Zigbee friendly names.
- A scan is **idempotent and append-only**: add previously unknown devices; skip *all* existing configured devices without modifications.
- Identity is **coordinator IEEE + device IEEE**, not the device friendly name.
- The **Supervisor App Options** hold the user-editable room/device/key-action bindings and desired device modes. HA template passports are removed.
- Dispatcher interprets only configured supported key actions and executes their corresponding HA commands.
- Mode Keeper enforces saved relay settings where supported, and Maintenance Mode temporarily overrides eligible modes without rewriting saved settings, then restores each device's individually configured state.
- A battery device without relays is a pure input device. Never fabricate relays, keys, actions, capabilities or successful commands.
- Do not modify the old AQPM2 controller or allow overlapping dispatchers before E2E migration acceptance.

## Environment and upgrade contract

This App is intended for HAOS Supervisor, MQTT and Zigbee2MQTT; Home Assistant supplies Area/Device Registries and execution of configured targets. Python logic lives in `rootfs/app/`, persistent state will live under `/data`. No private household bindings are committed.

**This stage is a source-only scaffold with manual boot and no GHCR release**. Do not deploy it as a working controller. Future production versions will use the immutable image and release workflow required by repository standards.

See [DOCS.md](DOCS.md) for the design contract, and [DigitalHouses standards](../docs/README.md).

## Developer verification

```bash
python -m compileall -q digitalhouses_aqara_switch_app/rootfs/app digitalhouses_aqara_switch_app/tests
python -m unittest discover -s digitalhouses_aqara_switch_app/tests -v
bash -n digitalhouses_aqara_switch_app/rootfs/run.sh
python scripts/validate_repository.py
```
