from typing import Any

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import TimestampedBase


class Character(TimestampedBase):
    __tablename__ = "characters"

    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)

    name: Mapped[str] = mapped_column(String(80))
    race: Mapped[str] = mapped_column(String(60), default="")
    klass: Mapped[str] = mapped_column(String(60), default="")
    background: Mapped[str] = mapped_column(String(60), default="")
    alignment: Mapped[str] = mapped_column(String(40), default="")
    level: Mapped[int] = mapped_column(Integer, default=1)
    xp: Mapped[int] = mapped_column(Integer, default=0)

    hp_current: Mapped[int] = mapped_column(Integer, default=0)
    hp_max: Mapped[int] = mapped_column(Integer, default=0)
    hp_temp: Mapped[int] = mapped_column(Integer, default=0)
    ac: Mapped[int] = mapped_column(Integer, default=10)

    ability_scores_json: Mapped[dict[str, Any]] = mapped_column(default=dict)  # str..cha
    proficiencies_json: Mapped[dict[str, Any]] = mapped_column(default=dict)  # skills, saves, tools
    spell_slots_json: Mapped[dict[str, Any]] = mapped_column(default=dict)  # {"1": {"max":2,"used":0}}
    resources_json: Mapped[dict[str, Any]] = mapped_column(default=dict)  # hit dice, feature charges
    conditions_json: Mapped[list[Any]] = mapped_column(default=list)
    death_saves_json: Mapped[dict[str, Any]] = mapped_column(default=dict)  # {"successes":0,"failures":0}
    currency_json: Mapped[dict[str, Any]] = mapped_column(default=dict)  # cp/sp/ep/gp/pp
    # skills detail, features, spells known/prepared, personality, notes, speed, senses…
    sheet_json: Mapped[dict[str, Any]] = mapped_column(default=dict)

    notes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(10), default="draft")  # draft|active|retired|dead
