"""Output safety checks: verbatim secret-leak detection.

Not bulletproof against paraphrase — the real defenses are prompt framing and
DM oversight — but catches the embarrassing copy-paste failure mode.
"""

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import NPC, Campaign, Quest, Scene

SHINGLE_WORDS = 8


def _shingles(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9']+", text.lower())
    return {
        " ".join(words[i : i + SHINGLE_WORDS])
        for i in range(len(words) - SHINGLE_WORDS + 1)
    }


async def scan_for_secret_leaks(
    db: AsyncSession, campaign: Campaign, scene: Scene, narration: str
) -> str | None:
    """Return a short description of the leaked secret, or None."""
    if not narration or len(narration) < 60:
        return None
    secrets: list[tuple[str, str]] = []
    if scene.dm_notes:
        secrets.append(("scene notes", scene.dm_notes))
    for npc in (
        await db.execute(
            select(NPC).where(NPC.campaign_id == campaign.id, NPC.secrets != ""))
    ).scalars():
        secrets.append((f"{npc.name}'s secret", npc.secrets))
    for quest in (
        await db.execute(
            select(Quest).where(Quest.campaign_id == campaign.id, Quest.dm_notes != ""))
    ).scalars():
        secrets.append((f"quest '{quest.title}' notes", quest.dm_notes))

    narration_shingles = _shingles(narration)
    if not narration_shingles:
        return None
    for label, secret in secrets:
        if _shingles(secret) & narration_shingles:
            return label
    return None
