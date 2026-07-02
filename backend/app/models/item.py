from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import TimestampedBase


class Item(TimestampedBase):
    __tablename__ = "items"

    campaign_id: Mapped[str | None] = mapped_column(
        ForeignKey("campaigns.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(120), index=True)
    item_type: Mapped[str] = mapped_column(String(60), default="")  # weapon, armor, gear…
    rarity: Mapped[str] = mapped_column(String(30), default="common")
    description: Mapped[str] = mapped_column(Text, default="")
    properties_json: Mapped[dict[str, Any]] = mapped_column(default=dict)
    source: Mapped[str] = mapped_column(String(10), default="custom")  # srd | ai | custom


class InventoryEntry(TimestampedBase):
    __tablename__ = "inventory_entries"
    __table_args__ = (Index("ix_inventory_owner", "owner_type", "owner_id"),)

    item_id: Mapped[str] = mapped_column(ForeignKey("items.id"), index=True)
    owner_type: Mapped[str] = mapped_column(String(12))  # character | npc | location
    owner_id: Mapped[str] = mapped_column(String(32))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    equipped: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")
