from __future__ import annotations

import re
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
PACKAGES = APP_ROOT / "examples" / "packages"
EN_PACKAGE = PACKAGES / "dh_app_pve_notification_package.yaml"
RU_PACKAGE = PACKAGES / "locales" / "ru" / "dh_app_pve_notification_package.yaml"
DUPLICATE_EN_PACKAGE = PACKAGES / "locales" / "en" / "dh_app_pve_notification_package.yaml"
README = APP_ROOT / "README.md"

EXPECTED_AUTOMATIONS = {
    "dh_app_pve_live_problem_notifications",
    "dh_app_pve_ups_config_changed_notification",
    "dh_app_pve_startup_problem_reconciliation",
}

SHARED_CONTRACT_TOKENS = (
    "dh_app_pve_notification_package:",
    "event.dh_app_pve_diagnostic",
    "event.dh_app_pve_ups_diagnostic",
    "sensor.dh_app_pve_problems",
    "sensor.dh_app_pve_ups_problems",
    "binary_sensor.bs_global_system_boot_completed",
    "event: dh_app_pve_notification",
    "problem_started",
    "problem_updated",
    "problem_recovered",
    "config_changed",
)


def _read(path: Path) -> str:
    assert path.is_file(), f"missing required locale artifact: {path.relative_to(APP_ROOT)}"
    return path.read_text(encoding="utf-8")


def _automation_ids(text: str) -> set[str]:
    return set(re.findall(r"^\s*- id:\s*([a-z0-9_]+)\s*$", text, flags=re.MULTILINE))


def test_notification_locales_share_one_machine_contract() -> None:
    en = _read(EN_PACKAGE)
    ru = _read(RU_PACKAGE)

    assert not DUPLICATE_EN_PACKAGE.exists(), (
        "English is the canonical root package; do not keep a duplicate locale/en copy"
    )

    for text in (en, ru):
        assert _automation_ids(text) == EXPECTED_AUTOMATIONS
        for token in SHARED_CONTRACT_TOKENS:
            assert token in text

    assert "problem detected" in en
    assert "Temperature:" in en
    assert "UPS Trigger configuration changed" in en
    assert "active problems after startup" in en
    assert re.search(r"[А-Яа-яЁё]", en) is None

    assert "обнаружена проблема" in ru
    assert "Температура:" in ru
    assert "Конфигурация UPS Trigger изменена" in ru
    assert "активные проблемы после запуска" in ru


def test_readme_requires_exactly_one_notification_locale() -> None:
    readme = _read(README)

    assert "examples/packages/dh_app_pve_notification_package.yaml" in readme
    assert "examples/packages/locales/ru/dh_app_pve_notification_package.yaml" in readme
    assert "Install exactly one notification locale" in readme

def test_startup_reconciliation_requires_fresh_current_process_publication() -> None:
    for text in (_read(EN_PACKAGE), _read(RU_PACKAGE)):
        assert "sensor.dh_app_pve_agent_started" in text
        assert "sensor.dh_app_pve_last_publication" in text
        assert "sensor.dh_app_pve_ups_last_publication" in text
        assert "wait_template:" in text
        assert "wait.completed" in text


def test_live_notification_presentation_fails_visibly_on_contract_error() -> None:
    for text in (_read(EN_PACKAGE), _read(RU_PACKAGE)):
        live = text.split("- id: dh_app_pve_ups_config_changed_notification", 1)[0]
        assert "kind: contract_error" in live
        assert "severity: error" in live
        assert "notification_title | trim" not in live
        assert "notification_message | trim" not in live


def test_ru_startup_ups_problems_use_problem_ids_not_legacy_summary() -> None:
    ru = _read(RU_PACKAGE)
    assert "Активная проблема UPS" not in ru
    for problem_id in (
        "nut_unavailable",
        "on_battery",
        "low_battery",
        "overload",
        "replace_battery",
        "bypass",
        "power_state_unknown",
    ):
        assert problem_id in ru



def _startup_section(text: str) -> str:
    return text.split("- id: dh_app_pve_startup_problem_reconciliation", 1)[1]


def test_startup_reconciliation_has_no_silent_contract_fallbacks() -> None:
    forbidden = (
        "as_timestamp(started, 0)",
        "as_timestamp(published, 0)",
        "| int(0)",
        "| default(",
        "get('metric', '')",
        "get('object_id', 'Proxmox')",
        "get('summary', 'Active problem')",
        "get('problem_id', '')",
        "Unknown UPS problem",
        "Неизвестная проблема UPS",
    )

    for text in (_read(EN_PACKAGE), _read(RU_PACKAGE)):
        startup = _startup_section(text)
        for token in forbidden:
            assert token not in startup, (
                f"startup reconciliation must not silently fallback contract data: {token}"
            )


def test_startup_reconciliation_validates_retained_aggregate_contract() -> None:
    for text in (_read(EN_PACKAGE), _read(RU_PACKAGE)):
        startup = _startup_section(text)

        for token in (
            "is_number(problem_count)",
            "severity is string",
            "active is sequence",
            "active is not string",
            "active | count == problem_count | int",
            "item is not mapping",
            "'problem_id' not in item",
            "'category' not in item",
            "'severity' not in item",
            "'object_id' not in item",
            "'object_name' not in item",
            "'metric' not in item",
            "'value' not in item",
            "'average' not in item",
            "'threshold' not in item",
            "kind: contract_error",
            "severity: error",
        ):
            assert token in startup


def test_startup_reconciliation_surfaces_freshness_failure() -> None:
    for text in (_read(EN_PACKAGE), _read(RU_PACKAGE)):
        startup = _startup_section(text)

        assert "as_timestamp(started, none)" in startup
        assert "as_timestamp(published, none)" in startup
        assert "continue_on_timeout: true" in startup
        assert "failure_class: freshness_timeout" in startup
        assert "kind: contract_error" in startup


def test_notification_package_no_longer_accepts_legacy_schema_v1_events() -> None:
    for text in (_read(EN_PACKAGE), _read(RU_PACKAGE)):
        live = text.split("- id: dh_app_pve_ups_config_changed_notification", 1)[0]
        assert "attrs.schema_version == 1" not in live
        assert "attrs.schema_version == 2" in live

def _notification_event_blocks(text: str) -> list[str]:
    lines = text.splitlines()
    blocks: list[str] = []
    for index, line in enumerate(lines):
        if "- event: dh_app_pve_notification" not in line:
            continue
        indent = len(line) - len(line.lstrip())
        end = index + 1
        while end < len(lines):
            current = lines[end]
            if current.strip():
                current_indent = len(current) - len(current.lstrip())
                if current_indent <= indent:
                    break
            end += 1
        blocks.append("\n".join(lines[index:end]))
    return blocks


def test_localized_notifications_use_notification_envelope_v1() -> None:
    required = (
        "notification_schema_version: 1",
        "source:",
        "kind:",
        "severity:",
        "title:",
        "message:",
    )
    for path in (EN_PACKAGE, RU_PACKAGE):
        blocks = _notification_event_blocks(_read(path))
        assert blocks, f"{path}: expected localized notification events"
        for block in blocks:
            for token in required:
                assert token in block, f"{path}: notification envelope missing {token}"


def test_contract_error_notifications_have_required_diagnostics() -> None:
    for path in (EN_PACKAGE, RU_PACKAGE):
        blocks = _notification_event_blocks(_read(path))
        contract_errors = [block for block in blocks if "kind: contract_error" in block]
        assert contract_errors, f"{path}: expected contract_error notifications"
        for block in contract_errors:
            assert "notification_schema_version: 1" in block
            assert "severity: error" in block
            assert "contract:" in block
            assert "failure_class:" in block

