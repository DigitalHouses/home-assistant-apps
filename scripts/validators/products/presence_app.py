"""Presence pilot-specific repository compatibility contract."""
from pathlib import Path
import struct

from validators.common import fail, require_files


def validate_presence_network_policy(config: dict, version: str) -> None:
    """Scoped, reviewed experimental Presence on-link ARP network policy.

    The one-time phone registration probe needs on-link ARP. NET_RAW and
    host_network are allowed only for explicitly reviewed pilot versions, with protected Ingress and
    *without* additional broad Linux capabilities, host mounts or Docker API.
    Any later release requires an explicit new policy review.
    """
    if (config.get("full_access") or config.get("docker_api")
            or config.get("apparmor") is False
            or config.get("hassio_role", "default") != "default"
            or config.get("host_pid") or config.get("host_ipc")
            or config.get("host_dbus") or config.get("host_uts")
            or config.get("map")):
        fail("Presence cannot request host-wide access, unsafe mounts or elevated Supervisor role")
    if version in ("0.1.11", "0.1.12", "0.1.13", "0.1.14", "0.1.15", "0.1.16", "0.1.17", "0.1.18", "0.1.19", "0.1.20", "0.1.21"):
        if config.get("host_network") is not True or config.get("privileged") != ["NET_RAW"]:
            fail("Presence experimental registration pilot permits only host_network and NET_RAW for one-time ARP")
        if (config.get("ingress") is not True
                or config.get("ingress_port") != 8099
                or config.get("panel_admin") is not False
                or config.get("ports")):
            fail("Presence registration pilot requires authenticated Ingress with no exposed host ports")
    elif "privileged" in config or config.get("host_network"):
        fail("Unreviewed Presence version cannot request raw sockets or host networking")


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
    validate_presence_network_policy(config, version)
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
        app / "rootfs/app/dh_presence/notifications.py",
        app / "rootfs/app/dh_presence/registration.py",
        app / "rootfs/app/dh_presence/wifi.py",
        app / "tests/test_wifi.py",
        app / "tests/test_wifi_notifications.py",
        app / "tests/test_mqtt_source_availability.py",
        app / "rootfs/app/dh_presence/ui.py",
        app / "tests/test_registration.py",
        app / "tests/test_ingress.py",
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
