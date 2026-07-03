from typing import Any

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import TimestampedBase


class Location(TimestampedBase):
    __tablename__ = "locations"

    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), index=True)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("locations.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(20), default="settlement")
    # world | region | settlement | dungeon | building | room | wilderness
    name: Mapped[str] = mapped_column(String(120), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    dm_notes: Mapped[str] = mapped_column(Text, default="")
    tags_json: Mapped[list[Any]] = mapped_column(default=list)
    created_by: Mapped[str] = mapped_column(String(10), default="dm")  # dm | ai


class Faction(TimestampedBase):
    __tablename__ = "factions"

    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    goals: Mapped[str] = mapped_column(Text, default="")
    dm_notes: Mapped[str] = mapped_column(Text, default="")
    relationships_json: Mapped[list[Any]] = mapped_column(default=list)  # [{faction_id, stance}]
    created_by: Mapped[str] = mapped_column(String(10), default="dm")


class Quest(TimestampedBase):
    __tablename__ = "quests"

    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), index=True)
    scene_id: Mapped[str | None] = mapped_column(String(32), nullable=True)  # origin scene
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(12), default="rumored")
    # rumored | active | completed | failed
    summary: Mapped[str] = mapped_column(Text, default="")
    dm_notes: Mapped[str] = mapped_column(Text, default="")  # hidden objectives / twists
    objectives_json: Mapped[list[Any]] = mapped_column(default=list)  # [{text, done}]
    rewards_json: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_by: Mapped[str] = mapped_column(String(10), default="dm")


class WorldEvent(TimestampedBase):
    """Append-only continuity log: 'the party burned the mill in Barrowdown'."""

    __tablename__ = "world_events"

    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), index=True)
    scene_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    description: Mapped[str] = mapped_column(Text)
    entity_refs_json: Mapped[list[Any]] = mapped_column(default=list)
    world_visibility: Mapped[bool] = mapped_column(default=True)  # relevant to other scenes?
