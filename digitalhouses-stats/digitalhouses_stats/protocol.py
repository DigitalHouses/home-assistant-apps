from __future__ import annotations

import re
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator


SUPPORTED_SCHEMA = 1
SUPPORTED_POLICY_VERSION = 1
ALLOWED_PRODUCTS = frozenset(
    {
        "digitalhouses_pve_agent",
        "digitalhouses_plex_agent",
        "digitalhouses_recorder_app",
        "digitalhouses_speedtest_app",
    }
)

SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


class StrictPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HeartbeatPayload(StrictPayload):
    schema: int = Field(ge=1)
    telemetry_policy_version: int = Field(ge=1)
    installation_id: uuid.UUID
    product: str
    version: str

    @field_validator("schema")
    @classmethod
    def validate_schema(cls, value: int) -> int:
        if value != SUPPORTED_SCHEMA:
            raise ValueError("unsupported schema")
        return value

    @field_validator("telemetry_policy_version")
    @classmethod
    def validate_policy(cls, value: int) -> int:
        if value != SUPPORTED_POLICY_VERSION:
            raise ValueError("unsupported telemetry policy version")
        return value

    @field_validator("installation_id")
    @classmethod
    def validate_uuid4(cls, value: uuid.UUID) -> uuid.UUID:
        if value.version != 4:
            raise ValueError("installation_id must be UUIDv4")
        return value

    @field_validator("product")
    @classmethod
    def validate_product(cls, value: str) -> str:
        if value not in ALLOWED_PRODUCTS:
            raise ValueError("unsupported product")
        return value

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        if SEMVER_RE.fullmatch(value) is None:
            raise ValueError("version must be Semantic Version")
        return value


class DeletePayload(StrictPayload):
    schema: int = Field(ge=1)
    installation_id: uuid.UUID
    product: str

    @field_validator("schema")
    @classmethod
    def validate_schema(cls, value: int) -> int:
        if value != SUPPORTED_SCHEMA:
            raise ValueError("unsupported schema")
        return value

    @field_validator("installation_id")
    @classmethod
    def validate_uuid4(cls, value: uuid.UUID) -> uuid.UUID:
        if value.version != 4:
            raise ValueError("installation_id must be UUIDv4")
        return value

    @field_validator("product")
    @classmethod
    def validate_product(cls, value: str) -> str:
        if value not in ALLOWED_PRODUCTS:
            raise ValueError("unsupported product")
        return value
