"""Rolling memory: scene summaries and campaign recaps.

Summaries preserve the facts that matter months later: proper nouns, promises,
items gained/lost, unresolved hooks, NPC attitude changes.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.provider import TextDelta, get_provider
from app.models import Campaign, Message, Scene, Summary

log = logging.getLogger("landl.memory")

SUMMARIZE_EVERY = 40  # messages between rolling re-summaries
ROLLUP_EVERY = 5  # scene summaries between campaign "story so far" refreshes

SUMMARY_PROMPT = """Summarize this D&D scene transcript in at most 150 words.
Preserve: character and NPC proper nouns, places, items gained or lost, promises
made, unresolved hooks, and any NPC attitude changes. Write in past tense.
{hint}
TRANSCRIPT:
{transcript}

SUMMARY:"""

CAMPAIGN_SUMMARY_PROMPT = """You maintain the "story so far" for a long-running \
D&D campaign. Rewrite the campaign summary in at most 400 words, merging the \
previous summary with the new scene recaps. Preserve: proper nouns (characters, \
NPCs, places, factions), promises made, items gained or lost, unresolved hooks \
and mysteries, and the party's standing goals. Prefer dropping color over \
dropping facts. Write in past tense.

PREVIOUS SUMMARY:
{previous}

NEW SCENE RECAPS (oldest first):
{recaps}

UPDATED CAMPAIGN SUMMARY:"""


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

    # Let open clients refresh scene lists and "Previously on…" recaps.
    from app.api.scenes import SceneOut
    from app.realtime import events
    from app.realtime.hub import hub

    hub.broadcast(
        campaign.id,
        events.make_event(
            events.SCENE_UPDATED, campaign.id,
            SceneOut.model_validate(scene).model_dump(), scene.id,
        ),
    )

    await maybe_rollup_campaign(db, campaign)
    return summary


async def maybe_rollup_campaign(db: AsyncSession, campaign: Campaign) -> str | None:
    """Refresh campaign.summary ("the story so far") once ROLLUP_EVERY new scene
    recaps have accumulated since the last rollup. Each rollup leaves a
    campaign-scope Summary row behind, so the trigger is a pure row count:
    rollup N fires once N*ROLLUP_EVERY scene recaps exist."""
    from sqlalchemy import func

    scene_count = (
        await db.execute(
            select(func.count())
            .select_from(Summary)
            .where(Summary.campaign_id == campaign.id, Summary.scope == "scene")
        )
    ).scalar_one()
    rollup_count = (
        await db.execute(
            select(func.count())
            .select_from(Summary)
            .where(Summary.campaign_id == campaign.id, Summary.scope == "campaign")
        )
    ).scalar_one()
    if scene_count < (rollup_count + 1) * ROLLUP_EVERY:
        return None

    recaps = list(
        (
            await db.execute(
                select(Summary)
                .where(Summary.campaign_id == campaign.id, Summary.scope == "scene")
                .order_by(Summary.created_at.desc())
                .limit(ROLLUP_EVERY * 2)
            )
        ).scalars()
    )[::-1]
    try:
        summary = await _complete(
            CAMPAIGN_SUMMARY_PROMPT.format(
                previous=campaign.summary or "(none yet — the campaign just began)",
                recaps="\n---\n".join(r.content for r in recaps),
            )
        )
    except Exception as exc:
        log.warning("campaign rollup failed: %s", exc)
        return None
    if not summary:
        return None

    campaign.summary = summary
    db.add(Summary(campaign_id=campaign.id, scope="campaign", content=summary))
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


async def rollup_scene_by_id(scene_id: str, force: bool = False) -> None:
    """Background-task entry point with its own session: summarize a scene by id.
    force=True summarizes unconditionally (explicit scene end); otherwise only
    when the unsummarized backlog warrants it."""
    from app.db import get_sessionmaker

    async with get_sessionmaker()() as db:
        scene = await db.get(Scene, scene_id)
        if not scene:
            return
        campaign = await db.get(Campaign, scene.campaign_id)
        if not campaign:
            return
        try:
            if force:
                await summarize_scene(db, campaign, scene)
            else:
                await maybe_rollup(db, campaign, scene)
        except Exception:
            log.exception("background summarization failed (scene=%s)", scene_id)
