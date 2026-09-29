import pytest

from app.operation_status import operation_payload


def test_operation_payload_has_stable_public_shape():
    payload = operation_payload(
        "updating",
        started_at="2026-09-29T20:00:00+05:00",
    )

    assert payload == {
        "state": "updating",
        "started_at": "2026-09-29T20:00:00+05:00",
        "finished_at": None,
        "duration_seconds": None,
        "error": None,
    }


def test_operation_payload_clamps_negative_duration():
    payload = operation_payload("idle", duration_seconds=-1)
    assert payload["duration_seconds"] == 0.0


def test_operation_payload_rejects_unknown_state():
    with pytest.raises(ValueError):
        operation_payload("running")
