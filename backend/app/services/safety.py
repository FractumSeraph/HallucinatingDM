"""Output safety checks: verbatim secret-leak detection and model safety-refusal
detection (a local model breaking the fourth wall to decline fantasy violence).

Not bulletproof against paraphrase — the real defenses are prompt framing and
DM oversight — but catches the embarrassing copy-paste failure mode.
"""

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import NPC, Campaign, Quest, Scene

SHINGLE_WORDS = 8

# Assistant-style refusal openers. Deliberately strict multi-word phrases so
# in-fiction dialogue ("'I can't sell you that,' the shopkeep says") never
# matches — safety-tuned models refuse in recognizable assistant-speak.
REFUSAL_MARKERS = (
    "as an ai",
    "i'm sorry, but i can't",
    "i am sorry, but i can't",
    "i'm sorry, but i cannot",
    "i am sorry, but i cannot",
    "i can't assist",
    "i cannot assist",
    "i can't help with",
    "i cannot help with",
    "i can't create content",
    "i cannot create content",
    "i can't write content",
    "i cannot write content",
    "i can't continue with this",
    "i cannot continue with this",
    "i can't generate",
    "i cannot generate",
    "i must decline",
    "i'm not able to help",
    "i am not able to help",
    "i'm not comfortable",
    "i am not comfortable",
    "i don't feel comfortable",
    "content policy",
    "my guidelines",
    "against my programming",
    "violates my",
)


def looks_like_refusal(narration: str) -> bool:
    """True when narration reads as a model safety refusal rather than fiction.

    Only the opening of the text is scanned — refusals lead with the apology,
    while a character saying "I can't…" happens mid-scene in quoted dialogue.
    """
    head = narration.strip().lower()[:200].replace("’", "'")
    return any(marker in head for marker in REFUSAL_MARKERS)


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
