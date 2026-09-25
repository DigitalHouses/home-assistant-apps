import pytest

from app.machine_event_outbox import MachineEventOutbox
from app.state_store import StateStore


def test_enqueue_is_idempotent_and_persists_across_reload(tmp_path):
    store = StateStore(tmp_path / "machine_event_outbox.json")
    outbox = MachineEventOutbox(store)
    payload = {"event_type": "ups_status_changed"}

    assert outbox.enqueue("status:1", payload) is True
    assert outbox.enqueue("status:1", payload) is False
    assert [item.key for item in outbox.pending()] == ["status:1"]
    assert outbox.pending()[0].payload == payload

    reloaded = MachineEventOutbox(store)
    assert [item.key for item in reloaded.pending()] == ["status:1"]
    assert reloaded.pending()[0].payload["event_type"] == "ups_status_changed"


def test_acknowledge_removes_only_matching_event_and_persists(tmp_path):
    store = StateStore(tmp_path / "machine_event_outbox.json")
    outbox = MachineEventOutbox(store)
    outbox.enqueue("status:1", {"event_type": "ups_status_changed"})
    outbox.enqueue("battery:1", {"event_type": "battery_discharge_level_crossed"})

    outbox.acknowledge("status:1")

    assert [item.key for item in outbox.pending()] == ["battery:1"]
    assert [item.key for item in MachineEventOutbox(store).pending()] == ["battery:1"]


def test_acknowledge_unknown_key_is_noop(tmp_path):
    store = StateStore(tmp_path / "machine_event_outbox.json")
    outbox = MachineEventOutbox(store)
    outbox.enqueue("status:1", {"event_type": "ups_status_changed"})

    outbox.acknowledge("missing")

    assert [item.key for item in outbox.pending()] == ["status:1"]


def test_rejects_empty_keys_and_non_dict_payloads(tmp_path):
    outbox = MachineEventOutbox(StateStore(tmp_path / "machine_event_outbox.json"))

    with pytest.raises(ValueError):
        outbox.enqueue("", {"event_type": "ups_status_changed"})
    with pytest.raises(TypeError):
        outbox.enqueue("status:1", ["not", "a", "dict"])


def test_persisted_shape_is_versioned(tmp_path):
    store = StateStore(tmp_path / "machine_event_outbox.json")
    outbox = MachineEventOutbox(store)
    outbox.enqueue("status:1", {"event_type": "ups_status_changed"})

    assert store.load() == {
        "schema_version": 1,
        "pending": [
            {
                "key": "status:1",
                "payload": {"event_type": "ups_status_changed"},
            }
        ],
    }
