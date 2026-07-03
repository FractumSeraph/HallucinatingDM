from typing import Any

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import TimestampedBase


class SrdEntry(TimestampedBase):
    """Structured SRD 5.1 content (CC-BY-4.0), seeded from bundled JSON at boot.

    One table, kind-discriminated: race | class | background | spell | equipment |
    monster | feature | rule | condition | magic-item | level (class level tables).
    """

    __tablename__ = "srd_entries"
    __table_args__ = (UniqueConstraint("kind", "slug"),)

    kind: Mapped[str] = mapped_column(String(20), index=True)
    slug: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    data_json: Mapped[dict[str, Any]] = mapped_column(default=dict)
