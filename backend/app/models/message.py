from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import TimestampedBase


class Message(TimestampedBase):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("scene_id", "seq"),)

    scene_id: Mapped[str] = mapped_column(ForeignKey("scenes.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)  # monotonic per scene; ordering + resync
    author_type: Mapped[str] = mapped_column(String(10))  # player | dm | ai | system | tool
    author_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    character_id: Mapped[str | None] = mapped_column(
        ForeignKey("characters.id"), nullable=True
    )  # in-character speech
    kind: Mapped[str] = mapped_column(String(12), default="chat")
    # chat | narration | ooc | roll | tool_result | whisper | system
    content: Mapped[str] = mapped_column(Text, default="")  # markdown
    payload_json: Mapped[dict[str, Any]] = mapped_column(default=dict)  # roll/tool details
    visibility: Mapped[str] = mapped_column(String(10), default="all")  # all | dm | dm_ai
    struck: Mapped[bool] = mapped_column(Boolean, default=False)  # retconned by the DM


class DiceRoll(TimestampedBase):
    __tablename__ = "dice_rolls"

    scene_id: Mapped[str] = mapped_column(ForeignKey("scenes.id"), index=True)
    message_id: Mapped[str | None] = mapped_column(ForeignKey("messages.id"), nullable=True)
    roller_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    character_id: Mapped[str | None] = mapped_column(ForeignKey("characters.id"), nullable=True)
    roller_name: Mapped[str] = mapped_column(String(120), default="")
    expression: Mapped[str] = mapped_column(String(60))  # "2d6+3"
    rolls_json: Mapped[list[Any]] = mapped_column(default=list)  # individual dice faces
    modifier: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer)
    purpose: Mapped[str] = mapped_column(String(20), default="raw")
    # check | save | attack | damage | initiative | death_save | raw
    detail_json: Mapped[dict[str, Any]] = mapped_column(default=dict)  # dc, outcome, adv, crit
