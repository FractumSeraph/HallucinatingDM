"""Rolling memory: scene summaries and campaign recaps.

Summaries preserve the facts that matter months later: proper nouns, promises,
items gained/lost, unresolved hooks, NPC attitude changes.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.provider import TextDelta, get_provider
from app.models import Campaign, Message, Scene, Summary

log = logging.getLogger("hallucinatingdm.memory")

SUMMARIZE_EVERY = 40  # messages between rolling re-summaries

SUMMARY_PROMPT = """Summarize this D&D scene transcript in at most 150 words.
Preserve: character and NPC proper nouns, places, items gained or lost, promises
made, unresolved hooks, and any NPC attitude changes. Write in past tense.
{hint}
TRANSCRIPT:
{transcript}

SUMMARY:"""


async def _complete(prompt: str) -> str:
    provider = await get_provider()
    out = ""
    async for event in provider.chat(
        [{"role": "user", "content": prompt}], temperature=0.3, max_tokens=400
    ):
        if isinstance(event, TextDelta):
            out += event.text
    return out.strip()


async def summarize_scene(
    db: AsyncSession, campaign: Campaign, scene: Scene, hint: str = ""
) -> str | None:
    messages = list(
        (
            await db.execute(
                select(Message)
                .where(
                    Message.scene_id == scene.id,
                    Message.seq > scene.summary_upto_seq,
                    Message.struck.is_(False),
                    Message.visibility == "all",
                )
                .order_by(Message.seq)
                .limit(200)
            )
        ).scalars()
    )
    if len(messages) < 4:
        return None

    transcript = "\n".join(
        f"{m.author_type}: {m.content[:400]}" for m in messages if m.content
    )[:14000]
    prefix = f"Earlier in this scene: {scene.summary}\n\n" if scene.summary else ""
    try:
        summary = await _complete(
            SUMMARY_PROMPT.format(
                transcript=prefix + transcript,
                hint=f"Also make sure to mention: {hint}" if hint else "",
            )
        )
    except Exception as exc:
        log.warning("scene summarization failed: %s", exc)
        return None
    if not summary:
        return None

    scene.summary = summary
    scene.summary_upto_seq = messages[-1].seq
    db.add(
        Summary(campaign_id=campaign.id, scope="scene", ref_id=scene.id, content=summary)
    )
    await db.commit()
    return summary


async def maybe_rollup(db: AsyncSession, campaign: Campaign, scene: Scene) -> None:
    """Called after each AI turn: refresh the rolling scene summary if the
    unsummarized window is getting long."""
    from sqlalchemy import func

    latest_seq = (
        await db.execute(
            select(func.coalesce(func.max(Message.seq), 0)).where(
                Message.scene_id == scene.id
            )
        )
    ).scalar_one()
    if latest_seq - scene.summary_upto_seq >= SUMMARIZE_EVERY:
        await summarize_scene(db, campaign, scene)
