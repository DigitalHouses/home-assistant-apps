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
