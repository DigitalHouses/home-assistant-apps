from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
CARD = ROOT / "examples" / "dh_pve_agent_shutdown_readiness_card.yaml"


def _text() -> str:
    return CARD.read_text(encoding="utf-8")


def test_shutdown_readiness_card_uses_canonical_backend_entities():
    assert CARD.is_file()
    text = _text()

    for entity_id in (
        "sensor.dh_pve_agent_ups_shutdown_readiness",
        "sensor.dh_pve_agent_ups_guest_shutdown_budget",
        "sensor.dh_pve_agent_ups_shutdown_budget",
    ):
        assert entity_id in text


def test_shutdown_readiness_card_uses_backend_budget_and_readiness_without_join_scan():
    text = _text()

    assert "sensor.dh_pve_agent_ups_guest_shutdown_budget" in text
    assert "sensor.dh_pve_agent_ups_shutdown_budget" in text
    assert "sensor.dh_pve_agent_ups_shutdown_readiness" in text
    assert "running_guests" in text
    assert "shutdown_sequence" in text
    assert "states.sensor" not in text
    assert "states.binary_sensor" not in text
    assert "proxmox_metric" not in text


def test_shutdown_readiness_card_contains_no_legacy_public_entity_ids():
    text = _text()

    assert ".dh_app_pve_" not in text
    assert re.search(r"\.dh_pve_(?!agent_)", text) is None


def test_shutdown_readiness_card_keeps_compact_original_layout():
    text = _text()

    assert text.startswith("type: markdown\ncontent: >\n")
    assert "### ⚙️ Конфигурация shutdown в PVE" in text
    assert "▶️ Гости (" in text
    assert "🖥️ PVE:" in text
    assert "⏱️ **ИТОГО:" in text
    assert "🔌 **Цепочка выключения**" in text
    assert "type: vertical-stack" not in text
    assert "Параметры выключения" not in text
    assert "Последняя остановка PVE" not in text
    assert "Как настроить UPS, NUT" not in text


def test_shutdown_readiness_card_translates_machine_issues_for_people():
    text = _text()

    for wording in (
        "UPS · нет связи через NUT",
        "NUT · настройки автоматического выключения недоступны",
        "PVE · не назначен главным сервером UPS (NUT PRIMARY)",
        "NUT · служба monitor не запущена",
        "PVE · команда выключения от UPS не активирована",
        "UPS · не удалось определить задержку включения после возврата питания",
        "PVE · предыдущий shutdown завершился некорректно",
        "shutdown близко к timeout",
        "превышен shutdown timeout",
        "потребовалось принудительное выключение",
    ):
        assert wording in text

    assert "{{ issue }}" not in text
