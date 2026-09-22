from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import text

from digitalhouses_stats.db import engine
from digitalhouses_stats.main import app


client = TestClient(app)


def reset_database() -> None:
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM heartbeats"))
        connection.execute(text("DELETE FROM installations"))


def test_healthz() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_heartbeat_history_and_authenticated_delete() -> None:
    reset_database()

    installation_id = str(uuid.uuid4())
    token = "ab" * 32
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "CF-IPCountry": "KZ",
    }

    payload = {
        "schema": 1,
        "telemetry_policy_version": 1,
        "installation_id": installation_id,
        "product": "digitalhouses_pve_agent",
        "version": "0.5.8",
    }

    first = client.post("/v1/heartbeat", json=payload, headers=headers)
    assert first.status_code == 204

    payload["version"] = "0.5.9"
    second = client.post("/v1/heartbeat", json=payload, headers=headers)
    assert second.status_code == 204

    with engine.begin() as connection:
        rows = connection.execute(
            text(
                """
                SELECT version, country, received_at
                FROM heartbeats
                ORDER BY id
                """
            )
        ).mappings().all()

    assert [row["version"] for row in rows] == ["0.5.8", "0.5.9"]
    assert [row["country"] for row in rows] == ["KZ", "KZ"]
    assert all(row["received_at"] is not None for row in rows)

    bad_headers = dict(headers)
    bad_headers["Authorization"] = f"Bearer {'cd' * 32}"
    rejected = client.post("/v1/heartbeat", json=payload, headers=bad_headers)
    assert rejected.status_code == 401

    delete_payload = {
        "schema": 1,
        "installation_id": installation_id,
        "product": "digitalhouses_pve_agent",
    }
    deleted = client.request(
        "DELETE",
        "/v1/installation",
        json=delete_payload,
        headers=headers,
    )
    assert deleted.status_code == 204

    with engine.begin() as connection:
        installations = connection.execute(
            text("SELECT count(*) FROM installations")
        ).scalar_one()
        heartbeats = connection.execute(
            text("SELECT count(*) FROM heartbeats")
        ).scalar_one()

    assert installations == 0
    assert heartbeats == 0


def test_token_cannot_take_over_existing_installation() -> None:
    reset_database()

    installation_id = str(uuid.uuid4())
    payload = {
        "schema": 1,
        "telemetry_policy_version": 1,
        "installation_id": installation_id,
        "product": "digitalhouses_recorder_app",
        "version": "0.1.9",
    }

    first = client.post(
        "/v1/heartbeat",
        json=payload,
        headers={
            "Authorization": f"Bearer {'11' * 32}",
            "Content-Type": "application/json",
            "CF-IPCountry": "DE",
        },
    )
    assert first.status_code == 204

    second = client.post(
        "/v1/heartbeat",
        json=payload,
        headers={
            "Authorization": f"Bearer {'22' * 32}",
            "Content-Type": "application/json",
            "CF-IPCountry": "DE",
        },
    )
    assert second.status_code == 401

    with engine.begin() as connection:
        count = connection.execute(text("SELECT count(*) FROM heartbeats")).scalar_one()

    assert count == 1

def test_oversized_telemetry_body_is_rejected() -> None:
    response = client.post(
        "/v1/heartbeat",
        content=b"x" * 2049,
        headers={
            "Authorization": f"Bearer {'aa' * 32}",
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 413
