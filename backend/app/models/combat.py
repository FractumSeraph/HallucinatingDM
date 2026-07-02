from typing import Any

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import TimestampedBase


class CombatEncounter(TimestampedBase):
    __tablename__ = "combat_encounters"

    scene_id: Mapped[str] = mapped_column(ForeignKey("scenes.id"), index=True)
    status: Mapped[str] = mapped_column(String(10), default="setup")  # setup | active | ended
    round: Mapped[int] = mapped_column(Integer, default=1)
    active_combatant_id: Mapped[str | None] = mapped_column(String(32), nullable=True)


class Combatant(TimestampedBase):
    __tablename__ = "combatants"

    encounter_id: Mapped[str] = mapped_column(ForeignKey("combat_encounters.id"), index=True)
    ref_type: Mapped[str] = mapped_column(String(12))  # character | npc | monster
    ref_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    name: Mapped[str] = mapped_column(String(120))  # "Goblin 3"
    initiative: Mapped[int] = mapped_column(Integer, default=0)
    # Monsters/NPCs snapshot HP here; characters delegate to their sheet.
    hp_current: Mapped[int | None] = mapped_column(nullable=True)
    hp_max: Mapped[int | None] = mapped_column(nullable=True)
    ac: Mapped[int | None] = mapped_column(nullable=True)
    conditions_json: Mapped[list[Any]] = mapped_column(default=list)
    stat_block_json: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    defeated: Mapped[bool] = mapped_column(default=False)
