"""On-demand action suggestions for players who don't know what to try.

New players freeze at "what do I even type?" — this asks the model for three
short, concrete, in-character options based on the live scene. Always returns
something: if the model is unreachable or rambles unparseably, a generic set
keeps the button useful.
"""

import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Character, Message, Scene

log = logging.getLogger("hallucinatingdm.suggestions")

MAX_SUGGESTIONS = 4

FALLBACK_SUGGESTIONS = [
    "I take a careful look around — what stands out?",
    "I talk to the nearest person and ask what's going on.",
    "I check my gear and get ready for trouble.",
]

SUGGEST_PROMPT = """You are helping a brand-new D&D player decide what to do next.

Scene: {scene_name}{scene_summary}
Their character: {character}
Recent play (newest last):
{transcript}

Suggest exactly 3 short actions this character could plausibly take right now.
One per line, numbered 1-3, written in first person ("I ..."), at most 12
words each. Make them varied — one social, one active, one cautious or
clever. No explanations, no extra text."""

_LINE = re.compile(r"^\s*(?:\d+[.)]|[-•*])\s*(.+?)\s*$")


def _parse(raw: str) -> list[str]:
    out: list[str] = []
    for line in raw.splitlines():
        m = _LINE.match(line)
        if m:
            text = m.group(1).strip().strip('"')
            if 3 <= len(text) <= 160:
                out.append(text)
    return out[:MAX_SUGGESTIONS]


async def suggest_actions(db: AsyncSession, scene: Scene, user_id: str) -> list[str]:
    character = (
        await db.execute(
            select(Character).where(
                Character.campaign_id == scene.campaign_id,
                Character.user_id == user_id,
                Character.status == "active",
            )
        )
    ).scalars().first()
    char_line = (
        f"{character.name}, a level {character.level} {character.race} {character.klass}"
        if character
        else "(no character yet — suggest observing and talking)"
    )

    recent = list(
        (
            await db.execute(
                select(Message)
                .where(
                    Message.scene_id == scene.id,
                    Message.visibility == "all",
                    Message.struck.is_(False),
                )
                .order_by(Message.seq.desc())
                .limit(10)
            )
        ).scalars()
    )[::-1]
    transcript = "\n".join(
        f"{m.author_type}: {m.content[:300]}" for m in recent if m.content
    ) or "(the scene has just begun)"

    prompt = SUGGEST_PROMPT.format(
        scene_name=scene.name,
        scene_summary=f" — {scene.summary[:300]}" if scene.summary else "",
        character=char_line,
        transcript=transcript,
    )

    try:
        from app.ai.memory import _complete

        raw = await _complete(prompt)
    except Exception as exc:
        log.warning("action suggestions failed: %s", exc)
        return list(FALLBACK_SUGGESTIONS)

    return _parse(raw) or list(FALLBACK_SUGGESTIONS)
