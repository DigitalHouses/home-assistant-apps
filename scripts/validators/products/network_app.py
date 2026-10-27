"""Product-specific pilot contract for the Ingress-only Network App."""
from __future__ import annotations

import struct
from pathlib import Path

from validators.common import fail, require_files


def validate_network(root: Path, app: Path, context: dict) -> None:
    config = context["config"]
    if config.get("name") != "DigitalHouses Network App":
        fail("Network App canonical display name changed")
    if config.get("stage") != "experimental":
        fail("Network App must be experimental until real scanner acceptance")
    if config.get("ingress") is not True or config.get("ingress_port") != 8099:
        fail("Network App requires authenticated Ingress on internal port 8099")
    if config.get("panel_admin") is not True:
        fail("Network App settings require an HA administrator")
    if config.get("image"):
        fail("Network App foundation must use Supervisor source build, not an unpublished image")
    if (config.get("full_access") or config.get("docker_api")
            or config.get("host_network") or config.get("host_pid")
            or config.get("host_dbus") or config.get("apparmor") is False
            or config.get("privileged") or config.get("map")
            or config.get("ports") or config.get("ports_description")):
        fail("Foundation preview cannot request host privileges or expose ports")
    if context["version"] != "0.1.0":
        fail("Network App pilot security policy requires review for every new version")
    require_files(root, [
        app / "icon.png", app / "logo.png",
        app / "go.mod",
        app / "cmd/dh-network/main.go",
        app / "cmd/dh-network/main_test.go",
        app / "cmd/dh-network/ui/index.html",
        app / "rootfs/app/preflight.py",
        app / "tests/test_preflight.py",
    ])
    for filename, dims in (("icon.png", (128,128)), ("logo.png", (250,100))):
        data = (app / filename).read_bytes()[:24]
        if len(data) != 24 or data[:8] != bytes.fromhex("89504e470d0a1a0a"):
            fail(f"Network App {filename} is not a valid PNG")
        if struct.unpack(">II", data[16:24]) != dims:
            fail(f"Network App {filename} has incorrect dimensions")
