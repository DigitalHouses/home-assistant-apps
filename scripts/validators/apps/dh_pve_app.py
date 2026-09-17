from __future__ import annotations

from pathlib import Path
from typing import Any

from validators.common import fail, require_files

EXPECTED_VERSION = "0.5.0"
EXPECTED_TOPIC_PREFIX = "DigitalHouses/Global/dh_pve_app"
EXPECTED_DEVICE_NAME = "DH PVE"
EXPECTED_REFRESH_ENTITY = "button.dh_app_pve_refresh"
EXPECTED_LAST_REFRESH_ENTITY = "sensor.dh_app_pve_last_refresh"


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
            app / "VERSION",
            app / "requirements.txt",
            app / "app/config.py",
            app / "app/topics.py",
            app / "app/discovery.py",
            app / "app/discovery_metrics.py",
            app / "app/discovery_guest.py",
            app / "app/discovery_groups.py",
            app / "app/discovery_ups_groups.py",
            app / "app/diagnostic_events.py",
            app / "app/runtime_dynamic.py",
            app / "app/runtime_problems.py",
            app / "app/ups_health.py",
            app / "app/ups_problems.py",
            app / "app/ups_group_runtime.py",
            app / "app/pve_cache.py",
            app / "app/disk_temperature.py",
            app / "app/collectors/guests.py",
            app / "app/topology.py",
            app / "app/production_v1.py",
            app / "app/production_guest.py",
            app / "app/shutdown_history.py",
            app / "app/shutdown_integration.py",
            app / "app/shutdown_discovery.py",
            app / "app/mqtt_bridge.py",
            app / "app/main.py",
            app / "examples/dh_pve_app.conf.example",
            app / "examples/dh_app_pve_dashboard.yaml",
            app / "examples/dh_app_pve_ups_dashboard.yaml",
            app / "examples/dh_app_pve_shutdown_readiness_card.yaml",
            app / "examples/packages/dh_app_pve_package.yaml",
            app / "systemd/dh_pve_app.service",
        ],
    )

    if context.get("type") != "linux_agent":
        fail("DH PVE must remain a linux_agent")

    version = (app / "VERSION").read_text(encoding="utf-8").strip()
    if context.get("version") != EXPECTED_VERSION or version != EXPECTED_VERSION:
        fail(f"DH PVE release version must be {EXPECTED_VERSION}")

    _require_text(
        app / "app/config.py",
        (f'DEFAULT_TOPIC_PREFIX = "{EXPECTED_TOPIC_PREFIX}"',),
        "MQTT",
    )
    _require_text(
        app / "app/topics.py",
        (
            'device_id = f"dh_app_pve_{identity.instance_id}"',
            'diagnostic_event=f"{base}/event/diagnostic"',
            'device_id = f"dh_app_pve_ups_{identity.instance_id}"',
            'previous_device_id = f"dh_pve_ups_{identity.instance_id}"',
            'legacy_device_id = f"dh_ups_{identity.instance_id}"',
            "legacy_discoveries=(",
        ),
        "canonical topics",
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
        "metric Discovery intermediate",
    )
    _require_text(
        app / "app/discovery_groups.py",
        (
            'object_id.startswith("dh_pve_")',
            '"dh_app_pve_" + object_id.removeprefix("dh_pve_")',
            '"default_entity_id": "sensor.dh_app_pve_problems"',
            '"default_entity_id": "event.dh_app_pve_diagnostic"',
            'entity_id="binary_sensor.dh_app_pve_cpu_temperature_problem"',
            'entity_id=f"binary_sensor.dh_app_pve_storage_{slug}_percent_used_problem"',
            'entity_id=f"binary_sensor.dh_app_pve_disk_{slug}_smart_problem"',
            'entity_id=f"binary_sensor.dh_app_pve_gpu_{slug}_temperature_problem"',
            '"problem_started"',
            '"problem_recovered"',
            '"problem_updated"',
        ),
        "canonical ready-state Discovery",
    )
    _require_text(
        app / "app/discovery_ups_groups.py",
        (
            'return value.replace(".dh_pve_ups_", ".dh_app_pve_ups_", 1)',
            'return value.replace(".dh_ups_", ".dh_app_pve_ups_", 1)',
            '"default_entity_id": f"binary_sensor.dh_app_pve_ups_{problem_id}_problem"',
            '"default_entity_id": "sensor.dh_app_pve_ups_problems"',
            '"default_entity_id": "event.dh_app_pve_ups_diagnostic"',
            '"nut_unavailable": "NUT unavailable"',
            '"power_state_unknown": "Power state unknown"',
            '"problem_started"',
            '"problem_recovered"',
            '"problem_updated"',
            '"config_changed"',
            '"ups_status_changed"',
            '"battery_discharge_level_crossed"',
            '"battery_fully_charged"',
            '"shutdown_committed"',
        ),
        "canonical UPS ready-state Discovery",
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
        "guest Discovery intermediate",
    )
    _require_text(
        app / "app/shutdown_discovery.py",
        (
            'entity_id="sensor.dh_pve_previous_shutdown"',
            'entity_id="sensor.dh_pve_shutdown_history"',
            'entity_id=f"sensor.dh_pve_{kind}_{_slug(guest_id)}_shutdown"',
            '"default_entity_id": "sensor.dh_pve_ups_guest_shutdown_budget"',
            '"default_entity_id": "sensor.dh_pve_ups_shutdown_readiness"',
            "route_pve_discovery_groups(",
            "route_ups_discovery_groups(",
        ),
        "shutdown Discovery intermediate",
    )
    _require_text(
        app / "app/ups_health.py",
        (
            "class UpsProblemObservation",
            "def ups_problem_observations(",
            'problem_id="nut_unavailable"',
            'problem_id="on_battery"',
            'problem_id="low_battery"',
            'problem_id="overload"',
            'problem_id="replace_battery"',
            'problem_id="bypass"',
            'problem_id="power_state_unknown"',
            "snapshot-derived problem states are deliberately",
        ),
        "UPS health policy",
    )
    _require_text(
        app / "app/ups_problems.py",
        (
            "class UpsProblemEngine",
            'category="ups"',
            '"problem_started" if state.active else "problem_recovered"',
            "ups_problem_observations(",
            "def aggregate(self) -> ProblemAggregate:",
        ),
        "UPS problem engine",
    )
    _require_text(
        app / "app/ups_group_runtime.py",
        (
            "self.problem_engine = UpsProblemEngine(",
            "def _flush_pending_problem_transitions(self) -> bool:",
            "def _republish_problem_snapshot(self) -> bool:",
            "self.bridge.publish_ups_diagnostic_event(event.as_payload())",
            "if not self._flush_pending_problem_transitions():",
            "self._observe_problem_snapshot(None, nut_available=False)",
        ),
        "UPS problem runtime",
    )
    _require_text(
        app / "app/mqtt_bridge.py",
        (
            "def publish_ups_problem_state(self, problem_id: str, active: bool) -> bool:",
            "def publish_ups_problem_aggregate(self, count: int) -> bool:",
            "def publish_ups_problem_presentation(self, payload: dict[str, object]) -> bool:",
            "def publish_ups_diagnostic_event(self, payload: dict[str, object]) -> bool:",
            "for topic in self.ups_topics.legacy_discoveries:",
        ),
        "UPS MQTT transport",
    )

    _require_text(
        app / "examples/packages/dh_app_pve_package.yaml",
        (
            "sensor.dh_app_pve_cpu_usage",
            "sensor.dh_app_pve_storage_*_percent_used",
            "sensor.dh_app_pve_ups_status",
            "logbook:",
        ),
        "HA package",
    )
    _require_text(
        app / "examples/dh_app_pve_dashboard.yaml",
        (
            "sensor.dh_app_pve_problems",
            "button.dh_app_pve_refresh",
            "number.dh_app_pve_cpu_temperature_threshold",
            "number.dh_app_pve_storage_percent_used_threshold",
        ),
        "PVE dashboard",
    )
    _require_text(
        app / "examples/dh_app_pve_ups_dashboard.yaml",
        (
            "sensor.dh_app_pve_ups_status",
            "sensor.dh_app_pve_ups_problems",
            "sensor.dh_app_pve_ups_battery_charger_status",
            "'charging': 'Заряжается'",
            "'floating': 'Поддержание заряда'",
            "binary_sensor.dh_app_pve_ups_on_battery_problem",
            "button.dh_app_pve_ups_refresh",
        ),
        "UPS dashboard",
    )
    _require_text(
        app / "examples/dh_app_pve_shutdown_readiness_card.yaml",
        (
            "sensor.dh_app_pve_previous_shutdown",
            "sensor.dh_app_pve_shutdown_history",
            "sensor.dh_app_pve_ups_shutdown_readiness",
            "sensor.dh_app_pve_ups_guest_shutdown_budget",
            "shutdown_reason",
            "shutdown_clean",
        ),
        "shutdown readiness card",
    )

    ups_discovery_source = (app / "app/discovery_ups_groups.py").read_text(
        encoding="utf-8"
    )
    for forbidden in (
        "status_ru",
        "problems_details",
        "value_json.summary",
        "value_json.details",
    ):
        if forbidden in ups_discovery_source:
            fail(f"DH PVE UPS Discovery depends on removed presentation field: {forbidden}")

    package = (app / "examples/packages/dh_app_pve_package.yaml").read_text(
        encoding="utf-8"
    )
    for forbidden in (
        "sensor.dh_app_pve_*",
        "binary_sensor.dh_app_pve_*",
        "sensor.dh_pve_",
        "binary_sensor.dh_pve_",
        "event.dh_app_pve_",
        "input_number:",
        "automation:",
    ):
        if forbidden in package:
            fail(f"DH PVE HA package must remain explicit/lightweight: {forbidden}")

    pve_dashboard = (app / "examples/dh_app_pve_dashboard.yaml").read_text(
        encoding="utf-8"
    )
    haos_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            app / "examples/dh_app_pve_dashboard.yaml",
            app / "examples/dh_app_pve_ups_dashboard.yaml",
            app / "examples/dh_app_pve_shutdown_readiness_card.yaml",
        )
    )
    for forbidden in (
        ".dh_pve_",
        ".dh_ups_",
        "input_number.dh_proxmox_",
        "states.sensor",
        "states.binary_sensor",
    ):
        if forbidden in haos_source:
            fail(f"DH PVE canonical HAOS examples contain legacy/business logic: {forbidden}")

    # auto-entities is presentation-only and is allowed only for the PVE
    # inventory collections whose membership is dynamic. It must not return to
    # the UPS/readiness examples or be used as a problem-discovery mechanism.
    strict_haos_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            app / "examples/dh_app_pve_ups_dashboard.yaml",
            app / "examples/dh_app_pve_shutdown_readiness_card.yaml",
        )
    )
    if "custom:auto-entities" in strict_haos_source:
        fail("DH PVE UPS/readiness UI must not use auto-entities")

    if pve_dashboard.count("type: custom:auto-entities") != 4:
        fail("DH PVE dashboard must use auto-entities only for 4 dynamic inventory collections")
    for required in (
        "proxmox_section: storage",
        "proxmox_section: disk",
        "proxmox_section: guests",
        "proxmox_subject: vm",
        "proxmox_subject: lxc",
        "attribute: proxmox_sort_key",
    ):
        if required not in pve_dashboard:
            fail(f"DH PVE inventory auto-entities contract changed: {required}")

    for legacy_name in (
        "dh_pve_dashboard.yaml",
        "dh_pve_ups_dashboard.yaml",
        "dh_pve_shutdown_readiness_card.yaml",
    ):
        if (app / "examples" / legacy_name).exists():
            fail(f"DH PVE legacy HAOS example must be removed: {legacy_name}")

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
            '"disk_temperature": self.disk_temperature',
            '"smart": self.smart',
            '"gpu": self.gpu',
        ),
        "guest-aware collectors",
    )
    _require_text(
        app / "app/topology.py",
        (
            'read_pve_vmlist(',
            'read_pve_rrd(',
            'path = self.pve_root / directory / f"{guest_id}.conf"',
            'current_vms, current_lxcs = self._guest_lists()',
        ),
        "cache-first topology",
    )
    _require_text(
        app / "app/shutdown_integration.py",
        (
            "class ShutdownAwareTopologyManager",
            "class ShutdownAwareProductionCollectors",
            "class ShutdownAwareUpsRuntime",
            '"shutdown_timeout_seconds": timeout',
            'fields["shutdown_readiness"]',
            "shutdown_policy_issues(",
        ),
        "shutdown runtime",
    )
    _require_text(
        app / "app/main.py",
        (
            "ProblemAwareRuntime(",
            "ShutdownAwareProductionCollectors(",
            "ShutdownAwareTopologyManager(runner=_run)",
            "build_shutdown_aware_pve_discovery_payload(",
            "ShutdownHistoryTracker(",
            "FAST_SECONDS = 10.0",
            "SLOW_SECONDS = 60.0",
            "HEALTH_SECONDS = 3600.0",
            'for name in ("cpu", "memory", "fans"):',
            'for name in ("guests", "storage", "gpu", "disk_temperature"):',
            'scheduler.add("smart", interval_seconds=HEALTH_SECONDS',
            'static_collectors=("topology", "host")',
            'slow_tasks=("guests", "storage", "gpu", "disk_temperature")',
            "read_pve_version(",
        ),
        "runtime",
    )
    _require_text(
        app / "app/runtime_dynamic.py",
        (
            '"setting_fast_poll_interval_seconds": "number"',
            '"setting_disk_poll_interval_seconds": "number"',
        ),
        "retired poll control cleanup",
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
