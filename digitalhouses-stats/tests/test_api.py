from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import text

from digitalhouses_stats.db import engine
from digitalhouses_stats.dashboard_api import app as dashboard_app
from digitalhouses_stats.main import app as telemetry_app


telemetry_client = TestClient(telemetry_app)
dashboard_client = TestClient(dashboard_app)


def reset_database() -> None:
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM heartbeats"))
        connection.execute(text("DELETE FROM installations"))


def test_healthz() -> None:
    response = telemetry_client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_empty_dashboard_summary() -> None:
    reset_database()

    response = dashboard_client.get("/v1/stats/summary")
    assert response.status_code == 200
    assert response.json() == {
        "observed_installations": 0,
        "active_24h": 0,
        "active_7d": 0,
        "active_30d": 0,
        "heartbeats": 0,
        "last_heartbeat": None,
    }


def test_empty_dashboard_products_lists_full_catalog() -> None:
    reset_database()

    response = dashboard_client.get("/v1/stats/products")
    assert response.status_code == 200

    rows = response.json()
    assert [row["product"] for row in rows] == [
        "digitalhouses_pve_agent",
        "digitalhouses_plex_agent",
        "digitalhouses_recorder_app",
        "digitalhouses_speedtest_app",
        "digitalhouses_backblaze_app",
        "digitalhouses_internet_app",
        "digitalhouses_climate_app",
    ]
    assert all(row["observed_installations"] == 0 for row in rows)
    assert all(row["active_24h"] == 0 for row in rows)
    assert all(row["active_7d"] == 0 for row in rows)
    assert all(row["active_30d"] == 0 for row in rows)


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

    first = telemetry_client.post("/v1/heartbeat", json=payload, headers=headers)
    assert first.status_code == 204

    payload["version"] = "0.5.9"
    second = telemetry_client.post("/v1/heartbeat", json=payload, headers=headers)
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
    rejected = telemetry_client.post("/v1/heartbeat", json=payload, headers=bad_headers)
    assert rejected.status_code == 401

    delete_payload = {
        "schema": 1,
        "installation_id": installation_id,
        "product": "digitalhouses_pve_agent",
    }
    deleted = telemetry_client.request(
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

    first = telemetry_client.post(
        "/v1/heartbeat",
        json=payload,
        headers={
            "Authorization": f"Bearer {'11' * 32}",
            "Content-Type": "application/json",
            "CF-IPCountry": "DE",
        },
    )
    assert first.status_code == 204

    second = telemetry_client.post(
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
    response = telemetry_client.post(
        "/v1/heartbeat",
        content=b"x" * 2049,
        headers={
            "Authorization": f"Bearer {'aa' * 32}",
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 413



def _send_heartbeat(
    *,
    installation_id: str,
    token_hex_pair: str,
    product: str,
    version: str,
    country: str,
) -> None:
    response = telemetry_client.post(
        "/v1/heartbeat",
        json={
            "schema": 1,
            "telemetry_policy_version": 1,
            "installation_id": installation_id,
            "product": product,
            "version": version,
        },
        headers={
            "Authorization": f"Bearer {token_hex_pair * 32}",
            "Content-Type": "application/json",
            "CF-IPCountry": country,
        },
    )
    assert response.status_code == 204


def test_local_stats_use_latest_installation_state() -> None:
    reset_database()

    pve_id = str(uuid.uuid4())
    recorder_id = str(uuid.uuid4())
    plex_id = str(uuid.uuid4())

    _send_heartbeat(
        installation_id=pve_id,
        token_hex_pair="11",
        product="digitalhouses_pve_agent",
        version="0.5.8",
        country="KZ",
    )
    _send_heartbeat(
        installation_id=pve_id,
        token_hex_pair="11",
        product="digitalhouses_pve_agent",
        version="0.5.10",
        country="KZ",
    )
    _send_heartbeat(
        installation_id=recorder_id,
        token_hex_pair="22",
        product="digitalhouses_recorder_app",
        version="0.1.9",
        country="DE",
    )
    _send_heartbeat(
        installation_id=plex_id,
        token_hex_pair="33",
        product="digitalhouses_plex_agent",
        version="0.5.0",
        country="US",
    )

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE heartbeats
                SET received_at = now() - interval '10 days'
                WHERE installation_id = :installation_id
                """
            ),
            {"installation_id": plex_id},
        )

    summary = dashboard_client.get("/v1/stats/summary")
    assert summary.status_code == 200
    summary_payload = summary.json()
    assert summary_payload["observed_installations"] == 3
    assert summary_payload["active_24h"] == 2
    assert summary_payload["active_7d"] == 2
    assert summary_payload["active_30d"] == 3
    assert summary_payload["heartbeats"] == 4
    assert isinstance(summary_payload["last_heartbeat"], str)
    assert summary_payload["last_heartbeat"].endswith("+00:00")

    products = dashboard_client.get("/v1/stats/products")
    assert products.status_code == 200
    by_product = {row["product"]: row for row in products.json()}
    assert by_product["digitalhouses_pve_agent"]["observed_installations"] == 1
    assert by_product["digitalhouses_pve_agent"]["active_7d"] == 1
    assert by_product["digitalhouses_plex_agent"]["observed_installations"] == 1
    assert by_product["digitalhouses_plex_agent"]["active_7d"] == 0
    assert by_product["digitalhouses_backblaze_app"]["observed_installations"] == 0
    assert by_product["digitalhouses_climate_app"]["observed_installations"] == 0
    assert by_product["digitalhouses_internet_app"]["name"] == "Internet App"

    versions = dashboard_client.get("/v1/stats/versions")
    assert versions.status_code == 200
    version_rows = versions.json()
    assert not any(
        row["product"] == "digitalhouses_pve_agent"
        and row["version"] == "0.5.8"
        for row in version_rows
    )
    assert any(
        row["product"] == "digitalhouses_pve_agent"
        and row["version"] == "0.5.10"
        and row["observed_installations"] == 1
        and row["active_7d"] == 1
        for row in version_rows
    )

    pve_versions = dashboard_client.get(
        "/v1/stats/versions",
        params={"product": "digitalhouses_pve_agent"},
    )
    assert pve_versions.status_code == 200
    assert pve_versions.json() == [
        {
            "product": "digitalhouses_pve_agent",
            "version": "0.5.10",
            "name": "PVE Agent",
            "observed_installations": 1,
            "active_7d": 1,
            "active_30d": 1,
        }
    ]

    countries = dashboard_client.get("/v1/stats/countries")
    assert countries.status_code == 200
    by_country = {row["country"]: row for row in countries.json()}
    assert by_country["KZ"]["observed_installations"] == 1
    assert by_country["KZ"]["active_7d"] == 1
    assert by_country["DE"]["active_7d"] == 1
    assert by_country["US"]["active_7d"] == 0

    history = dashboard_client.get("/v1/stats/history", params={"days": 2})
    assert history.status_code == 200
    points = history.json()
    assert len(points) == 2
    assert points[-1]["active_installations"] == 2
    assert points[-1]["heartbeats"] == 3

    invalid = dashboard_client.get(
        "/v1/stats/versions",
        params={"product": "not_a_product"},
    )
    assert invalid.status_code == 400


def test_stats_history_days_validation() -> None:
    too_small = dashboard_client.get("/v1/stats/history", params={"days": 0})
    assert too_small.status_code == 422

    too_large = dashboard_client.get("/v1/stats/history", params={"days": 3651})
    assert too_large.status_code == 422



def test_public_telemetry_process_does_not_expose_stats() -> None:
    response = telemetry_client.get("/v1/stats/summary")
    assert response.status_code == 404


def test_dashboard_healthz() -> None:
    response = dashboard_client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
