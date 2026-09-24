from __future__ import annotations

import re
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
PACKAGES = APP_ROOT / "examples" / "packages"
EN_PACKAGE = PACKAGES / "dh_app_pve_notification_local_package.yaml"
RU_PACKAGE = PACKAGES / "locales" / "ru" / "dh_app_pve_notification_local_package.yaml"
README = APP_ROOT / "README.md"

EXPECTED_TRIGGER_IDS = {
    "problem_started",
    "problem_updated",
    "problem_recovered",
    "ups_status_changed",
    "battery_discharge_level_crossed",
    "battery_fully_charged",
    "shutdown_committed",
    "config_changed",
}


def _read(path: Path) -> str:
    assert path.is_file(), f"missing required notification artifact: {path.relative_to(APP_ROOT)}"
    return path.read_text(encoding="utf-8")


def _trigger_ids(text: str) -> set[str]:
    return set(re.findall(r"^\s*id:\s*([a-z0-9_]+)\s*$", text, flags=re.MULTILINE))


def test_local_packages_use_simple_direct_event_flow() -> None:
    en = _read(EN_PACKAGE)
    ru = _read(RU_PACKAGE)

    for text in (en, ru):
        assert "trigger: event.received" in text
        assert "condition: trigger" in text
        assert "trigger.to_state.attributes" in text
        assert "actions:" in text
        assert "choose:" in text

        ids = _trigger_ids(text)
        assert EXPECTED_TRIGGER_IDS <= ids

        for forbidden in (
            "event: dh_app_pve_notification",
            "notification_schema_version",
            "contract_error",
            "failure_class",
            "source_schema_version",
            "startup_problem_reconciliation",
            "attrs.schema_version",
        ):
            assert forbidden not in text

    assert "action: persistent_notification.create" in en
    assert "action: script.write2log" in ru


def test_local_packages_keep_language_in_local_yaml() -> None:
    en = _read(EN_PACKAGE)
    ru = _read(RU_PACKAGE)

    assert "battery charged" in en
    assert "UPS Trigger configuration changed" in en
    assert re.search(r"[А-Яа-яЁё]", en) is None

    assert "батарея заряжена" in ru
    assert "Конфигурация UPS Trigger изменена" in ru


def test_readme_describes_local_notification_package() -> None:
    readme = _read(README)

    assert "dh_app_pve_notification_local_package.yaml" in readme
    assert "trigger.id" in readme
    assert "direct action" in readme
