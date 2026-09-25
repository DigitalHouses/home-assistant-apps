from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from digitalhouses_stats.country import country_from_cloudflare
from digitalhouses_stats.products import ALLOWED_PRODUCTS, PRODUCTS
from digitalhouses_stats.protocol import HeartbeatPayload
from digitalhouses_stats.security import token_hash, token_matches


def test_country_from_cloudflare() -> None:
    assert country_from_cloudflare("KZ") == "KZ"
    assert country_from_cloudflare("de") == "DE"
    assert country_from_cloudflare("T1") == "XX"
    assert country_from_cloudflare(None) == "XX"
    assert country_from_cloudflare("invalid") == "XX"


def test_token_hash_and_compare() -> None:
    token = "ab" * 32
    digest = token_hash(token)
    assert len(digest) == 64
    assert token_matches(token, digest)
    assert not token_matches("cd" * 32, digest)


def test_heartbeat_payload_accepts_protocol_v1() -> None:
    payload = HeartbeatPayload(
        schema=1,
        telemetry_policy_version=1,
        installation_id=uuid.uuid4(),
        product="digitalhouses_pve_agent",
        version="0.5.8",
    )
    assert payload.schema == 1


def test_heartbeat_payload_accepts_internet_app() -> None:
    payload = HeartbeatPayload(
        schema=1,
        telemetry_policy_version=1,
        installation_id=uuid.uuid4(),
        product="digitalhouses_internet_app",
        version="0.1.10",
    )
    assert payload.product == "digitalhouses_internet_app"


def test_heartbeat_payload_accepts_climate_app() -> None:
    payload = HeartbeatPayload(
        schema=1,
        telemetry_policy_version=1,
        installation_id=uuid.uuid4(),
        product="digitalhouses_climate_app",
        version="0.1.0",
    )
    assert payload.product == "digitalhouses_climate_app"


def test_product_registry_is_complete_and_drives_allowlist() -> None:
    assert [product.identifier for product in PRODUCTS] == [
        "digitalhouses_pve_agent",
        "digitalhouses_plex_agent",
        "digitalhouses_recorder_app",
        "digitalhouses_speedtest_app",
        "digitalhouses_backblaze_app",
        "digitalhouses_internet_app",
        "digitalhouses_climate_app",
    ]
    assert ALLOWED_PRODUCTS == {
        product.identifier
        for product in PRODUCTS
        if product.telemetry_allowed
    }


def test_heartbeat_payload_accepts_backblaze_app() -> None:
    payload = HeartbeatPayload(
        schema=1,
        telemetry_policy_version=1,
        installation_id=uuid.uuid4(),
        product="digitalhouses_backblaze_app",
        version="0.1.7",
    )
    assert payload.product == "digitalhouses_backblaze_app"


def test_heartbeat_payload_rejects_unknown_product() -> None:
    with pytest.raises(ValidationError):
        HeartbeatPayload(
            schema=1,
            telemetry_policy_version=1,
            installation_id=uuid.uuid4(),
            product="unknown_product",
            version="1.0.0",
        )


def test_heartbeat_payload_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        HeartbeatPayload(
            schema=1,
            telemetry_policy_version=1,
            installation_id=uuid.uuid4(),
            product="digitalhouses_pve_agent",
            version="0.5.8",
            hostname="must-not-be-accepted",
        )
