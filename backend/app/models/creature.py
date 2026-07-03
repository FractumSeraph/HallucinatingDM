from typing import Any

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import TimestampedBase


class NPC(TimestampedBase):
    __tablename__ = "npcs"

    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    role: Mapped[str] = mapped_column(String(120), default="")  # occupation / narrative role
    disposition: Mapped[str] = mapped_column(String(40), default="neutral")
    description: Mapped[str] = mapped_column(Text, default="")
    secrets: Mapped[str] = mapped_column(Text, default="")  # DM/AI-only, never shown to players
    location_id: Mapped[str | None] = mapped_column(ForeignKey("locations.id"), nullable=True)
    faction_id: Mapped[str | None] = mapped_column(ForeignKey("factions.id"), nullable=True)
    present_in_scene_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    stat_block_json: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    hp_current: Mapped[int | None] = mapped_column(nullable=True)
    conditions_json: Mapped[list[Any]] = mapped_column(default=list)
    aliases_json: Mapped[list[Any]] = mapped_column(default=list)
    created_by: Mapped[str] = mapped_column(String(10), default="dm")  # dm | ai
    status: Mapped[str] = mapped_column(String(10), default="active")  # active | dead | draft


class Monster(TimestampedBase):
    __tablename__ = "monsters"

    # NULL campaign_id = shared/global (e.g. AI-generated templates)
    campaign_id: Mapped[str | None] = mapped_column(
        ForeignKey("campaigns.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(120), index=True)
    cr: Mapped[str] = mapped_column(String(10), default="0")  # "1/4", "5", …
    stat_block_json: Mapped[dict[str, Any]] = mapped_column(default=dict)
    description: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(10), default="custom")  # srd | ai | custom
