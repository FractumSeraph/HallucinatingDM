from typing import Any

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import TimestampedBase


class Scene(TimestampedBase):
    __tablename__ = "scenes"

    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(10), default="main")  # main | side | solo
    status: Mapped[str] = mapped_column(String(10), default="active")  # active | idle | archived
    dm_mode: Mapped[str] = mapped_column(String(10), default="ai")  # human | assist | copilot | ai
    location_id: Mapped[str | None] = mapped_column(ForeignKey("locations.id"), nullable=True)
    party_json: Mapped[list[Any]] = mapped_column(default=list)  # character ids in scene
    dm_notes: Mapped[str] = mapped_column(Text, default="")  # scene-scoped secret prep
    scratch_json: Mapped[dict[str, Any]] = mapped_column(default=dict)  # "the door is barred"
    time_note: Mapped[str] = mapped_column(String(200), default="")  # when this scene happens
    summary: Mapped[str] = mapped_column(Text, default="")  # rolling AI-maintained recap
    summary_upto_seq: Mapped[int] = mapped_column(Integer, default=0)
    last_world_event_seen: Mapped[str | None] = mapped_column(String(32), nullable=True)
