from __future__ import annotations

from pathlib import Path
from typing import Any

from validators.common import fail, require_files

EXPECTED_TOPIC_PREFIX = "DigitalHouses/Global/dh_pve_app"
EXPECTED_DEVICE_NAME = "DH PVE"
EXPECTED_REFRESH_ENTITY = "button.dh_pve_refresh"
EXPECTED_LAST_REFRESH_ENTITY = "sensor.dh_pve_last_refresh"


def _require_text(path: Path, expected: tuple[str, ...], label: str) -> None:
    text = path.read_text(encoding="utf-8")
    for value in expected:
        if value not in text:
            fail(f"DH PVE {label} contract changed: {value}")


def validate_dh_pve_app(
    root: Path,
    app: Path,
    context: dict[str, Any],
) -> None:
    require_files(
        root,
        [
            app / "requirements.txt",
            app / "app/config.py",
            app / "app/topics.py",
            app / "app/discovery.py",
            app / "app/discovery_metrics.py",
            app / "app/discovery_guest.py",
            app / "app/runtime_dynamic.py",
            app / "app/collectors/guests.py",
            app / "app/topology.py",
            app / "app/production_v1.py",
            app / "app/production_guest.py",
            app / "app/main.py",
            app / "examples/dh_pve_app.conf.example",
            app / "systemd/dh_pve_app.service",
        ],
    )

    if context.get("type") != "linux_agent":
        fail("DH PVE must remain a linux_agent")

    _require_text(
        app / "app/config.py",
        (f'DEFAULT_TOPIC_PREFIX = "{EXPECTED_TOPIC_PREFIX}"',),
        "MQTT",
    )
    _require_text(
        app / "app/discovery.py",
        (
            f'"name": "{EXPECTED_DEVICE_NAME}"',
            f'"default_entity_id": "{EXPECTED_REFRESH_ENTITY}"',
            f'"default_entity_id": "{EXPECTED_LAST_REFRESH_ENTITY}"',
            '"payload_press": "PRESS"',
        ),
        "base Discovery",
    )
    _require_text(
        app / "app/discovery_metrics.py",
        (
            'entity_id="sensor.dh_pve_system"',
            'entity_id="sensor.dh_pve_cpu_usage"',
            'entity_id="sensor.dh_pve_cpu_temperature"',
            'entity_id="binary_sensor.dh_pve_cpu_throttling"',
            'entity_id="sensor.dh_pve_memory_usage"',
            'f"sensor.dh_pve_storage_{slug}_usage"',
            'f"sensor.dh_pve_disk_{slug}_health"',
            'f"sensor.dh_pve_gpu_{slug}_owner"',
            'f"sensor.dh_pve_fan_{slug}_rpm"',
            "'proxmox_integration':'dh_pve_app'",
            '"used_gib":',
            '"total_gib":',
        ),
        "metric Discovery",
    )
    _require_text(
        app / "app/discovery_guest.py",
        (
            'entity_id=f"sensor.dh_pve_{kind}_{_slug(guest_id)}_status"',
            'entity_id="sensor.dh_pve_vms" if kind == "vm" else "sensor.dh_pve_lxcs"',
            'entity_id=f"sensor.dh_pve_passthrough_{slug}"',
            'section="guests"',
            'subject="passthrough"',
        ),
        "guest Discovery",
    )

    discovery_metrics = (app / "app/discovery_metrics.py").read_text(
        encoding="utf-8"
    )
    if '"available_gib":' in discovery_metrics:
        fail("DH PVE storage UI contract must remain used/total, not free")

    _require_text(
        app / "app/production_v1.py",
        (
            "MISSING_CONFIRMATIONS = 3",
            'item["available"] = False',
            '"disk missing from authoritative SMART inventory"',
            '"source_type": "guest"',
            'data["primary_ip"] = primary_ip',
            'data["boot_time"] = boot_time_iso',
        ),
        "resilient collector",
    )
    _require_text(
        app / "app/production_guest.py",
        (
            "class GuestAwareProductionCollectors",
            '"topology": self.topology_inventory',
            '"guests": self.guests',
            '"smart": self.smart',
            '"gpu": self.gpu',
        ),
        "guest-aware collectors",
    )
    _require_text(
        app / "app/main.py",
        (
            "DynamicDiscoveryRuntime(",
            "GuestAwareProductionCollectors(",
            "TopologyManager(runner=_run)",
            "build_guest_aware_discovery_payload(",
            'scheduler.add("guests", interval_seconds=10.0',
            'scheduler.add("host", interval_seconds=86400.0',
        ),
        "runtime",
    )

    service = app / "systemd/dh_pve_app.service"
    _require_text(
        service,
        (
            "User=root",
            "WorkingDirectory=/opt/digitalhouses/dh_pve_app",
            (
                "ExecStart=/opt/digitalhouses/dh_pve_app/.venv/bin/python "
                "-m app.main --config /etc/dh_pve_app/dh_pve_app.conf "
                "--state-dir /var/lib/dh_pve_app"
            ),
            "Restart=on-failure",
        ),
        "systemd",
    )

    installer = (app / "install.sh").read_text(encoding="utf-8")
    for expected in (
        'APP_NAME="dh_pve_app"',
        'APP_DIR="/opt/digitalhouses/${APP_NAME}"',
        'CONFIG_DIR="/etc/${APP_NAME}"',
        'STATE_DIR="/var/lib/${APP_NAME}"',
        'if [[ ! -f "${CONFIG_FILE}" ]]; then',
        "nano /etc/dh_pve_app/dh_pve_app.conf",
        "--check-config",
    ):
        if expected not in installer:
            fail(f"DH PVE installer contract changed: {expected}")

    for forbidden in (
        "digitalhouses-proxmox-mqtt.sh",
        "/etc/cron.d/digitalhouses-proxmox-mqtt",
    ):
        if forbidden in installer:
            fail(f"DH PVE Phase 1 installer must not touch legacy agent: {forbidden}")

    app_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((app / "app").glob("*.py"))
    )
    if "digitalhouses_proxmox_" in app_source:
        fail("DH PVE source must not reuse legacy Home Assistant entity IDs")
