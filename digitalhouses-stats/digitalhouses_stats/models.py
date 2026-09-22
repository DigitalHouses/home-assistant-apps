from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class Installation(Base):
    __tablename__ = "installations"

    product: Mapped[str] = mapped_column(Text, primary_key=True)
    installation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    installation_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class Heartbeat(Base):
    __tablename__ = "heartbeats"
    __table_args__ = (
        ForeignKeyConstraint(
            ["product", "installation_id"],
            ["installations.product", "installations.installation_id"],
            ondelete="CASCADE",
        ),
        Index("ix_heartbeats_received_at", "received_at"),
        Index(
            "ix_heartbeats_product_installation_received_at",
            "product",
            "installation_id",
            "received_at",
        ),
        Index(
            "ix_heartbeats_product_version_received_at",
            "product",
            "version",
            "received_at",
        ),
        Index(
            "ix_heartbeats_country_received_at",
            "country",
            "received_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    product: Mapped[str] = mapped_column(Text, nullable=False)
    installation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    telemetry_policy_version: Mapped[int] = mapped_column(Integer, nullable=False)
