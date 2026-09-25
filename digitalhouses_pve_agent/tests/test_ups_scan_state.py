import importlib.util
from pathlib import Path

from app.config import UpsConfig
from app.state_store import StateStore
from app.ups_nut import NutReadError

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "app" / "ups_scan.py"


def _module():
    assert MODULE_PATH.is_file(), "ups_scan.py must implement persistent UPS provisioning"
    spec = importlib.util.spec_from_file_location("app.ups_scan", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_single_found_ups_is_selected_and_persisted(tmp_path: Path):
    module = _module()
    store = StateStore(tmp_path / "ups_selection.json")
    scanner = module.UpsScanner(
        UpsConfig(enabled=False),
        store,
        now_iso=lambda: "2026-09-12T20:00:00+05:00",
        list_reader=lambda config: ("ups",),
    )

    outcome = scanner.scan()

    assert outcome.result == "UPS найден: ups"
    assert outcome.count == 1
    assert outcome.names == ("ups",)
    assert outcome.selected_name == "ups"
    assert outcome.selection_changed is True
    assert store.load()["selected_name"] == "ups"
    assert outcome.payload()["last_scan"] == "2026-09-12T20:00:00+05:00"


def test_zero_results_do_not_remove_existing_selection(tmp_path: Path):
    module = _module()
    store = StateStore(tmp_path / "ups_selection.json")
    store.save({"selected_name": "ups"})
    scanner = module.UpsScanner(
        UpsConfig(enabled=False),
        store,
        now_iso=lambda: "2026-09-12T20:01:00+05:00",
        list_reader=lambda config: (),
    )

    outcome = scanner.scan()

    assert outcome.result == "UPS не найден"
    assert outcome.selected_name == "ups"
    assert outcome.selection_changed is False
    assert store.load()["selected_name"] == "ups"


def test_multiple_results_do_not_replace_existing_selection(tmp_path: Path):
    module = _module()
    store = StateStore(tmp_path / "ups_selection.json")
    store.save({"selected_name": "oldups"})
    scanner = module.UpsScanner(
        UpsConfig(enabled=False),
        store,
        now_iso=lambda: "2026-09-12T20:02:00+05:00",
        list_reader=lambda config: ("ups", "backup"),
    )

    outcome = scanner.scan()

    assert outcome.result == "Обнаружено несколько UPS"
    assert outcome.count == 2
    assert outcome.names == ("ups", "backup")
    assert outcome.selected_name == "oldups"
    assert outcome.selection_changed is False


def test_nut_error_is_reported_without_clearing_selection(tmp_path: Path):
    module = _module()
    store = StateStore(tmp_path / "ups_selection.json")
    store.save({"selected_name": "ups"})

    def fail(config):
        raise NutReadError("NUT недоступен")

    scanner = module.UpsScanner(
        UpsConfig(enabled=False),
        store,
        now_iso=lambda: "2026-09-12T20:03:00+05:00",
        list_reader=fail,
    )

    outcome = scanner.scan()

    assert outcome.result == "NUT недоступен"
    assert outcome.count == 0
    assert outcome.names == ()
    assert outcome.selected_name == "ups"
    assert outcome.selection_changed is False
    assert outcome.payload()["error"] == "NUT недоступен"
