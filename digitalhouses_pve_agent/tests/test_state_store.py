from pathlib import Path

import pytest

from app.state_store import StateStore, StateStoreError


def test_missing_state_loads_empty(tmp_path: Path):
    store = StateStore(tmp_path / "state.json")
    assert store.load() == {}


def test_save_and_load_round_trip(tmp_path: Path):
    path = tmp_path / "state.json"
    store = StateStore(path)
    data = {"settings": {"cpu_publish_delta": 7.0}, "daily": {"disk": 55.0}}

    store.save(data)

    assert store.load() == data
    assert not (tmp_path / "state.json.tmp").exists()


def test_corrupt_state_is_reported_not_silently_reset(tmp_path: Path):
    path = tmp_path / "state.json"
    path.write_text("{broken", encoding="utf-8")
    store = StateStore(path)

    with pytest.raises(StateStoreError, match="invalid persisted state"):
        store.load()
