import uuid
import time
import os
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def generate_uuid_v7() -> uuid.UUID:
    """Generate a UUID v7 (time-ordered, millisecond precision)."""
    timestamp_ms = int(time.time() * 1000)
    # 48 bits of unix timestamp (ms)
    uuid_int = (timestamp_ms & 0xFFFFFFFFFFFF) << 80
    # version 7
    uuid_int |= 0x7000 << 64
    # 12 bits of random
    rand_a = int.from_bytes(os.urandom(2), "big") & 0x0FFF
    uuid_int |= rand_a << 64
    # variant bits (10xx)
    uuid_int |= 0x8000000000000000
    # 62 bits of random
    rand_b = int.from_bytes(os.urandom(8), "big") & 0x3FFFFFFFFFFFFFFF
    uuid_int |= rand_b
    return uuid.UUID(int=uuid_int)


class Base(DeclarativeBase):
    pass


class UUIDPrimaryKey:
    """Mixin that adds a UUID v7 primary key column."""

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=generate_uuid_v7,
    )


class TimestampMixin:
    """Mixin that adds created_at and updated_at columns."""

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, onupdate=func.now(), nullable=True
    )
