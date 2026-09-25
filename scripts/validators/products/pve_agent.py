from __future__ import annotations

from pathlib import Path
from typing import Any

from validators.common import fail, require_files

EXPECTED_VERSION = "0.5.24"
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
            app / "app/pve_problem_events.py",
            app / "app/ups_event_context.py",
            app / "app/ups_health.py",
            app / "app/ups_problems.py",
            app / "app/ups_problem_events.py",
            app / "app/ups_group_runtime.py",
            app / "app/pve_cache.py",
            app / "app/disk_temperature.py",
            app / "app/fan_presence.py",
            app / "app/fan_calibration.py",
            app / "app/fan_hardware_beelink.py",
            app / "app/fan_runtime.py",
            app / "app/telemetry.py",
            app / "app/collectors/guests.py",
            app / "app/topology.py",
            app / "app/production_v1.py",
            app / "app/production_guest.py",
            app / "app/shutdown_history.py",
            app / "app/shutdown_integration.py",
            app / "app/shutdown_discovery.py",
            app / "app/mqtt_bridge.py",
            app / "app/uninstall_cleanup.py",
            app / "app/main.py",
            app / "examples/dh_pve_app.conf.example",
            app / "examples/dh_app_pve_dashboard.yaml",
            app / "examples/dh_app_pve_ups_dashboard.yaml",
            app / "examples/dh_app_pve_shutdown_readiness_card.yaml",
            app / "examples/packages/dh_app_pve_package.yaml",
            app / "examples/packages/dh_app_pve_notification_local_package.yaml",
            app / "examples/packages/locales/ru/dh_app_pve_notification_local_package.yaml",
            app / "systemd/dh_pve_app.service",
            app / "uninstall.sh",
            app / "dh_app_pve.txt",
        ],
    )

    if context.get("type") != "linux_agent":
        fail("DH PVE must remain a linux_agent")

    legacy_ui_package = app / "examples/packages/dh_app_pve_ui_package.yaml"
    if legacy_ui_package.exists():
        fail("DH PVE HA helpers must be consolidated into dh_app_pve_package.yaml")

    version = (app / "VERSION").read_text(encoding="utf-8").strip()
    if context.get("version") != EXPECTED_VERSION or version != EXPECTED_VERSION:
        fail(f"DH PVE release version must be {EXPECTED_VERSION}")

    _require_text(
        app / "app/config.py",
        (
            f'DEFAULT_TOPIC_PREFIX = "{EXPECTED_TOPIC_PREFIX}"',
            "class EventConfig:",
            "pve_problem_debounce_seconds: float = 30.0",
            '"pve_problem_debounce_seconds"',
        ),
        "MQTT/events",
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
            '"cpu_temperature_high"',
            '"cpu_temperature_normal"',
            '"cpu_throttling_started"',
            '"cpu_throttling_cleared"',
            '"storage_usage_high"',
            '"storage_usage_normal"',
            '"disk_temperature_high"',
            '"disk_temperature_normal"',
            '"gpu_temperature_high"',
            '"gpu_temperature_normal"',
            '"fan_control_restore_failed"',
            '"fan_control_restored"',
            '"disk_smart_failed"',
            '"disk_smart_restored"',
            '"default_entity_id": "sensor.dh_app_pve_app_version"',
            "{{ value_json.app_version | default('unknown') }}",
            '"default_entity_id": "sensor.dh_app_pve_agent_started"',
            "{{ value_json.agent_started_at | default(none) }}",
            '"default_entity_id": "binary_sensor.dh_app_pve_ups_configured"',
            "value_json.ups_configured",
        ),
        "canonical ready-state Discovery",
    )
    pve_discovery_source = (app / "app/discovery_groups.py").read_text(
        encoding="utf-8"
    )
    if '"problem_updated"' in pve_discovery_source:
        fail("DH PVE public Event Discovery must remain semantic-only")

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
            '"nut_unavailable"',
            '"nut_restored"',
            '"power_state_unknown"',
            '"power_state_restored"',
            '"line_power_lost"',
            '"line_power_restored"',
            '"low_battery_started"',
            '"low_battery_cleared"',
            '"high_battery_started"',
            '"high_battery_cleared"',
            '"replace_battery_started"',
            '"replace_battery_cleared"',
            '"bypass_started"',
            '"bypass_ended"',
            '"calibration_started"',
            '"calibration_ended"',
            '"output_off"',
            '"output_restored"',
            '"overload_started"',
            '"overload_cleared"',
            '"trim_started"',
            '"trim_ended"',
            '"boost_started"',
            '"boost_ended"',
            '"forced_shutdown_started"',
            '"forced_shutdown_cleared"',
            '"alarm_started"',
            '"alarm_cleared"',
            '"battery_discharge_level_crossed"',
            '"battery_fully_charged"',
            '"shutdown_committed"',
            '"config_changed"',
            '"quick_test_supported"',
            '"deep_test_supported"',
            '"stop_test_supported"',
            '"beeper_control_supported"',
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

    notification_packages = (
        app / "examples/packages/dh_app_pve_notification_local_package.yaml",
        app / "examples/packages/locales/ru/dh_app_pve_notification_local_package.yaml",
    )
    for notification_package in notification_packages:
        notification_source = notification_package.read_text(encoding="utf-8")
        for required in (
            "trigger: event.received",
            "condition: trigger",
            "trigger.to_state.attributes",
            "choose:",
            "id: cpu_temperature_high",
            "id: cpu_temperature_normal",
            "id: cpu_throttling_started",
            "id: cpu_throttling_cleared",
            "id: storage_usage_high",
            "id: storage_usage_normal",
            "id: disk_temperature_high",
            "id: disk_temperature_normal",
            "id: gpu_temperature_high",
            "id: gpu_temperature_normal",
            "id: fan_control_restore_failed",
            "id: fan_control_restored",
            "id: disk_smart_failed",
            "id: disk_smart_restored",
            "id: nut_unavailable",
            "id: nut_restored",
            "id: power_state_unknown",
            "id: power_state_restored",
            "id: line_power_lost",
            "id: line_power_restored",
            "id: low_battery_started",
            "id: low_battery_cleared",
            "id: high_battery_started",
            "id: high_battery_cleared",
            "id: replace_battery_started",
            "id: replace_battery_cleared",
            "id: bypass_started",
            "id: bypass_ended",
            "id: calibration_started",
            "id: calibration_ended",
            "id: output_off",
            "id: output_restored",
            "id: overload_started",
            "id: overload_cleared",
            "id: trim_started",
            "id: trim_ended",
            "id: boost_started",
            "id: boost_ended",
            "id: forced_shutdown_started",
            "id: forced_shutdown_cleared",
            "id: alarm_started",
            "id: alarm_cleared",
            "id: battery_discharge_level_crossed",
            "id: battery_fully_charged",
            "id: shutdown_committed",
            "id: config_changed",
            "temperature_c",
            "threshold_c",
            "cpu_frequency_mhz",
            "available_gib",
            "battery_runtime_seconds",
            "load_percent",
            "input_voltage_v",
            "output_voltage_v",
        ):
            if required not in notification_source:
                fail(
                    "DH PVE local notification flow changed: "
                    f"{notification_package}: {required}"
                )

        for forbidden in (
            "event: dh_app_pve_notification",
            "id: ups_status_changed",
            "id: problem_started",
            "id: problem_recovered",
            "id: problem_updated",
            "notification_schema_version",
            "contract_error",
            "failure_class",
            "source_schema_version",
            "startup_problem_reconciliation",
            "attrs.schema_version",
        ):
            if forbidden in notification_source:
                fail(
                    "DH PVE local notification package is unnecessarily complex: "
                    f"{notification_package}: {forbidden}"
                )

    en_notification = notification_packages[0].read_text(encoding="utf-8")
    ru_notification = notification_packages[1].read_text(encoding="utf-8")
    if "action: persistent_notification.create" not in en_notification:
        fail("DH PVE English local notification example must use a direct action")
    if "action: script.write2log" not in ru_notification:
        fail("DH PVE Russian site notification package must call write2log directly")

    ui_package = (
        app / "examples/packages/dh_app_pve_package.yaml"
    ).read_text(encoding="utf-8")
    close_after_success = ui_package.split(
        "- id: dh_app_pve_ups_trigger_close_after_success",
        1,
    )[1]
    for required in (
        "condition: template",
        "'event_type' in attrs",
        "attrs.event_type == 'config_changed'",
        "'schema_version' in attrs",
        "attrs.schema_version == 2",
        "'observed_at' in attrs",
        "attrs.observed_at is string",
        "'old_values' in attrs",
        "attrs.old_values is mapping",
        "'new_values' in attrs",
        "attrs.new_values is mapping",
        "attrs.previous_revision is number",
        "attrs.current_revision is number",
    ):
        if required not in close_after_success:
            fail(f"DH PVE UPS Trigger UI acknowledgement contract changed: {required}")

    for required in (
        "is_number(active_charge)",
        "is_number(active_reserve)",
        "is_number(draft_charge)",
        "is_number(draft_reserve)",
        "snapshot_charge:",
        "snapshot_reserve:",
        "is_number(snapshot_charge)",
        "is_number(snapshot_reserve)",
        "current_charge_raw:",
        "current_reserve_raw:",
        "active_charge_raw:",
        "active_reserve_raw:",
        "is_number(current_charge_raw)",
        "is_number(current_reserve_raw)",
        "is_number(active_charge_raw)",
        "is_number(active_reserve_raw)",
        "DH PVE UPS Trigger UI contract error:",
        "error: true",
    ):
        if required not in ui_package:
            fail(f"DH PVE UPS Trigger UI numeric contract changed: {required}")

    for forbidden in (
        "states('number.dh_app_pve_ups_shutdown_battery_charge_threshold') | float",
        "states('number.dh_app_pve_ups_shutdown_runtime_reserve') | float",
        "states('input_number.dh_app_pve_ups_trigger_snapshot_charge') | float",
        "states('input_number.dh_app_pve_ups_trigger_snapshot_reserve') | float",
    ):
        if forbidden in ui_package:
            fail(f"DH PVE UPS Trigger UI silently coerces required state: {forbidden}")

    _require_text(
        app / "examples/packages/dh_app_pve_package.yaml",
        (
            "sensor.dh_app_pve_cpu_usage",
            "sensor.dh_app_pve_storage_*_percent_used",
            "sensor.dh_app_pve_fan_*_speed",
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
            "binary_sensor.dh_app_pve_ups_configured",
            "ИБП не настроен",
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
        app / "app/fan_presence.py",
        (
            "class FanPresenceTracker",
            "streak >= 2",
            '"schema_version": 1',
            '"confirmed": sorted(self._confirmed)',
        ),
        "fan presence tracker",
    )
    _require_text(
        app / "app/production_v1.py",
        (
            "MISSING_CONFIRMATIONS = 3",
            '"candidate_ids": [fan.fan_id for fan in raw]',
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
            "problem_event_debounce_seconds=config.events.pve_problem_debounce_seconds",
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
            'fan_presence_store = StateStore(state_dir / "fans.json")',
            'StateStore(state_dir / "fan_calibration.json")',
            "DEFAULT_TELEMETRY_STATE_FILE",
            "_telemetry_state_file(state_dir)",
            "BeelinkIt8613FanAdapter()",
            "FanCalibrationManager(",
            "TelemetryClient(",
            "TelemetryRunner(",
            "telemetry_runner.start()",
            "telemetry_runner.stop()",
            "runtime.recover_fan_control()",
            "runtime.wait_fan_calibration()",
            "app_version=version",
            "ups_configured=selected_ups_name is not None",
            "runtime.set_ups_configured(True)",
            "--uninstall-mqtt-cleanup",
            "cleanup_mqtt(config, identity)",
        ),
        "runtime",
    )
    _require_text(
        app / "app/telemetry.py",
        (
            'PRODUCT = "digitalhouses_pve_agent"',
            '"/var/lib/digitalhouses/digitalhouses_pve_agent/telemetry.json"',
            '"schema": SCHEMA_VERSION',
            '"telemetry_policy_version": TELEMETRY_POLICY_VERSION',
            '"installation_id": self.installation_id',
            '"product": PRODUCT',
            '"version": self.version',
            'path="/v1/heartbeat"',
            'method="DELETE"',
            'path="/v1/installation"',
            "is_released_build(self.version, self.build_info_path)",
            "class TelemetryRunner",
        ),
        "telemetry client",
    )
    _require_text(
        app / "app/fan_calibration.py",
        (
            "class FanCalibrationRegistry",
            "class FanCalibrationManager",
            '"calibration_status": "calibrating"',
            '"calibration_status": "restore_failed"',
            '"max_rpm_source": "observed"',
            "OBSERVED_MAX_CONFIRMATIONS = 3",
            "self._lock.acquire(blocking=False)",
            "recover_pending",
        ),
        "fan calibration",
    )
    _require_text(
        app / "app/fan_hardware_beelink.py",
        (
            'profile_name = "beelink_it8613_v1"',
            'fan.chip == "it8613"',
            'fan.source_device == "it87.2608"',
            "fan.fan_index == 2",
            'self._write(pwm_path, "255")',
        ),
        "Beelink fan calibration profile",
    )

    _require_text(
        app / "app/pve_cache.py",
        (
            "def _static_version_payload(",
            'if str(key) != "tasklist"',
        ),
        "PVE static version fingerprint",
    )

    _require_text(
        app / "app/presentation.py",
        (
            '"value_appeared"',
        ),
        "first valid metric publication",
    )

    _require_text(
        app / "app/runtime_dynamic.py",
        (
            '"setting_fast_poll_interval_seconds": "number"',
            '"setting_disk_poll_interval_seconds": "number"',
            "def _split_component_tombstones(",
            "def _component_cleanup_payload(",
            "pending_tombstones",
        ),
        "retired poll control and dynamic component cleanup",
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

    config_example = (app / "examples/dh_pve_app.conf.example").read_text(encoding="utf-8")
    if "[telemetry]" not in config_example or "enabled = false" not in config_example:
        fail("DH PVE telemetry must remain explicit opt-in and default OFF")
    for expected in (
        "[events]",
        "pve_problem_debounce_seconds = 30",
    ):
        if expected not in config_example:
            fail(f"DH PVE event debounce example contract changed: {expected}")

    installer = (app / "install.sh").read_text(encoding="utf-8")
    for expected in (
        'APP_NAME="dh_pve_app"',
        'APP_DIR="/opt/digitalhouses/${APP_NAME}"',
        'CONFIG_DIR="/etc/${APP_NAME}"',
        'STATE_DIR="/var/lib/${APP_NAME}"',
        'TELEMETRY_STATE_DIR="/var/lib/digitalhouses/digitalhouses_pve_agent"',
        'if [[ ! -f "${CONFIG_FILE}" ]]; then',
        "nano /etc/dh_pve_app/dh_pve_app.conf",
        "--check-config",
        'chmod 0755 "${APP_DIR}/uninstall.sh"',
        'ROOT_GUIDE="/root/dh_app_pve.txt"',
        'cat "${APP_DIR}/dh_app_pve.txt"',
        '"[events]"',
        '"pve_problem_debounce_seconds = 30"',
    ):
        if expected not in installer:
            fail(f"DH PVE installer contract changed: {expected}")

    for forbidden in (
        "digitalhouses-proxmox-mqtt.sh",
        "/etc/cron.d/digitalhouses-proxmox-mqtt",
    ):
        if forbidden in installer:
            fail(f"DH PVE Phase 1 installer must not touch legacy agent: {forbidden}")

    cleanup_source = (app / "app/uninstall_cleanup.py").read_text(encoding="utf-8")
    for expected in (
        "build_topics(config.mqtt, identity)",
        "build_ups_topics(config.mqtt, identity)",
        '(topics.availability, "offline")',
        '(ups_topics.availability, "offline")',
        '(topics.discovery, "")',
        '(ups_topics.discovery, "")',
        "topics.legacy_discoveries",
        "ups_topics.legacy_discoveries",
        "qos=1",
        "retain=True",
    ):
        if expected not in cleanup_source:
            fail(f"DH PVE uninstall MQTT cleanup contract changed: {expected}")

    uninstaller = (app / "uninstall.sh").read_text(encoding="utf-8")
    for expected in (
        'CONFIG_DIR="/etc/${APP_NAME}"',
        'STATE_DIR="/var/lib/${APP_NAME}"',
        '"--purge"',
        'systemctl stop "${SERVICE_NAME}"',
        "--uninstall-mqtt-cleanup",
        'systemctl start "${SERVICE_NAME}"',
        'rm -rf -- "${APP_DIR}"',
        'rm -rf -- "${CONFIG_DIR}" "${STATE_DIR}" "${TELEMETRY_STATE_DIR}"',
        'ROOT_GUIDE="/root/dh_app_pve.txt"',
        'rm -f -- "${ROOT_GUIDE}"',
    ):
        if expected not in uninstaller:
            fail(f"DH PVE uninstaller contract changed: {expected}")

    _require_text(
        app / "dh_app_pve.txt",
        (
            "Установка",
            "Обновление",
            "systemctl status dh_pve_app",
            "/etc/dh_pve_app/dh_pve_app.conf",
            "--ups-policy-preflight",
            "/opt/digitalhouses/dh_pve_app/uninstall.sh",
            "--purge",
        ),
        "operational guide",
    )

    uninstaller_lower = uninstaller.lower()
    for forbidden in (
        "/etc/nut",
        "upsmon -c fsd",
        "upscmd",
        "load.off",
        "load.on",
        "apt-get remove",
        "apt remove",
        "apt purge",
        "haos",
        "mosquitto",
    ):
        if forbidden in uninstaller_lower:
            fail(f"DH PVE uninstaller crosses ownership/safety boundary: {forbidden}")

    for diagnostic_metadata_entity in (
        "sensor.dh_app_pve_app_version",
        "sensor.dh_app_pve_agent_started",
    ):
        if diagnostic_metadata_entity in package:
            fail(
                "DH PVE diagnostic metadata sensor must not be added to Recorder whitelist: "
                f"{diagnostic_metadata_entity}"
            )

    app_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((app / "app").glob("*.py"))
    )
    if "digitalhouses_proxmox_" in app_source:
        fail("DH PVE source must not reuse legacy Home Assistant entity IDs")
