import secrets
from typing import Any

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import TimestampedBase


def new_invite_code() -> str:
    return secrets.token_urlsafe(8)


class Campaign(TimestampedBase):
    __tablename__ = "campaigns"

    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    invite_code: Mapped[str] = mapped_column(
        String(24), unique=True, index=True, default=new_invite_code
    )
    # tone, rating, house_rules, ai_style, copilot gate list, model overrides…
    settings_json: Mapped[dict[str, Any]] = mapped_column(default=dict)
    world_clock: Mapped[str] = mapped_column(String(120), default="Day 1, morning")
    summary: Mapped[str] = mapped_column(Text, default="")


class CampaignMember(TimestampedBase):
    __tablename__ = "campaign_members"
    __table_args__ = (UniqueConstraint("campaign_id", "user_id"),)

    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(10))  # dm | player
