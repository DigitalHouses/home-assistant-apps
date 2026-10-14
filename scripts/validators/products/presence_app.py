"""Presence pilot-specific repository compatibility contract."""
from pathlib import Path
import struct

from validators.common import fail, require_files


def validate_presence(root: Path, app: Path, context: dict) -> None:
    version = context["version"]
    config = context["config"]
    if version != "0.1.1":
        # This validator must be updated when changing the pilot's runtime contract.
        if not isinstance(version, str) or not version:
            fail("Presence App version must be valid")
    if config.get("slug") != "digitalhouses_presence_app":
        fail("Presence App slug must remain canonical")
    if config.get("stage") != "experimental":
        fail("Presence App must remain experimental until acceptance")
    if config.get("image"):
        fail("Pilot uses Supervisor local build; no unpublished GHCR image")
    if config.get("homeassistant_api") is not True:
        fail("Presence App needs HA Core API")
    if "mqtt:need" not in config.get("services", []):
        fail("Presence App requires MQTT service")
    if "privileged" in config or config.get("host_network") or config.get("full_access"):
        fail("Unvalidated raw-socket or host privileges forbidden in GPS pilot")
    if config.get("options", {}).get("telemetry_enabled") is not False:
        fail("Pilot does not have telemetry integration")
    if config.get("options", {}).get("residents") != []:
        fail("Pilot must have zero residents until configured locally")
    if config.get("schema", {}).get("residents") != ["str"]:
        fail("Presence App must require exactly one device_tracker string per resident")

    require_files(root, [
        app / "icon.png", app / "logo.png",
        app / "rootfs/app/app.py",
        app / "rootfs/app/dh_presence/core.py",
        app / "rootfs/app/dh_presence/discovery.py",
        app / "rootfs/app/dh_presence/storage.py",
        app / "rootfs/app/dh_presence/modes.py",
        app / "tests/test_core.py",
        app / "tests/test_discovery.py",
        app / "tests/test_modes.py",
    ])
    for file, width, height in ((app / "icon.png", 128, 128), (app / "logo.png", 250, 100)):
        payload = file.read_bytes()[:24]
        if len(payload) != 24 or payload[:8] != bytes.fromhex("89504e470d0a1a0a"):
            fail(f"{file.name}: invalid PNG")
        if struct.unpack(">II", payload[16:24]) != (width, height):
            fail(f"{file.name}: wrong PNG dimensions")

    source = (app / "rootfs/app/dh_presence/discovery.py").read_text(encoding="utf-8")
    for required in (
        "DigitalHouses/Global/dh_presence_app", "homeassistant/device/dh_presence_app/config",
        "dh_presence_app_residents_home", "dh_presence_app_event",
        "dh_presence_app_version", "dh_presence_app_started_at", "dh_presence_app_mode",
    ):
        if required not in source:
            fail(f"Presence App missing stable MQTT contract: {required}")
