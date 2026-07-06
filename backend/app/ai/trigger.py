"""Bridges player messages to the AI DM agent loop.

Multiplayer turn-gathering: in an AI-run scene with more than one player
character, the DM waits until every participant has declared an action (posted
an in-character message or tapped Skip) before resolving the round, so one
player's message doesn't make the AI act before the others have spoken. The
human DM can force resolution ("Resolve now") if someone is AFK. Solo scenes
resolve immediately, exactly as before.

Declaration state is per-scene and in-memory — fine for this single-process
app; a restart mid-round just means players re-declare.
"""

import logging
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Character, Message, Scene
from app.realtime import events
from app.realtime.hub import hub

log = logging.getLogger("landl.trigger")

# scene_id -> set of character_ids that have declared this round
_declared: dict[str, set[str]] = defaultdict(set)


async def maybe_trigger_ai_turn(
    scene: Scene, message: Message, db: AsyncSession | None = None
) -> None:
    if scene.dm_mode not in ("ai", "copilot", "assist"):
        return
    if message.author_type not in ("player", "dm"):
        return
    if message.kind in ("ooc", "whisper"):
        return

    # A player's in-character action is a declaration to gather; the DM's own
    # messages and dice-roll responses continue the turn immediately.
    if message.author_type == "player" and message.kind == "chat" and db:
        if not message.character_id:
            # A player with no character can't act. If a party is mid-round,
            # treat it as table talk (don't cut the round short); with no
            # roster yet, behave as before and let the AI respond.
            if await _participants(db, scene):
                return
            _resolve(scene.id)
            return
        # In combat, initiative — not declaration-gathering — decides who may
        # act: the acting player's message must resolve at once, or the round
        # would wait on players who aren't allowed to act right now.
        from app.services.combat import get_active_encounter

        if await get_active_encounter(db, scene.id):
            _resolve(scene.id)
        else:
            await _declare(db, scene, message.character_id)
    else:
        _resolve(scene.id)


def _resolve(scene_id: str) -> None:
    """Clear the round and kick the AI turn."""
    _declared.pop(scene_id, None)
    from app.ai.dm_agent import reset_combat_chain, trigger_turn

    reset_combat_chain(scene_id)  # fresh player input re-arms combat auto-continue
    trigger_turn(scene_id)


async def _participants(db: AsyncSession, scene: Scene) -> set[str]:
    """Characters whose declaration the round waits for: active roster members
    who are conscious — an unconscious PC can't act, so they can't block."""
    ids = list(scene.party_json or [])
    if not ids:
        return set()
    rows = list(
        (
            await db.execute(
                select(Character.id, Character.user_id).where(
                    Character.id.in_(ids),
                    Character.status == "active",
                    Character.hp_current > 0,
                )
            )
        ).all()
    )
    # Don't wait on players who aren't even connected (closed laptop, dropped
    # phone): their character re-joins the round the moment they speak again.
    # When nobody is on a websocket (e.g. pure-REST clients), skip the filter.
    connected = hub.campaign_user_ids(scene.campaign_id)
    if connected:
        rows = [r for r in rows if r.user_id in connected]
    return {r.id for r in rows}


async def _declare(db: AsyncSession, scene: Scene, character_id: str) -> None:
    """Record a character's action for the round; resolve once everyone has."""
    # Join the character to the scene roster on first participation.
    if character_id not in (scene.party_json or []):
        scene.party_json = [*(scene.party_json or []), character_id]
        await db.commit()

    _declared[scene.id].add(character_id)
    expected = await _participants(db, scene)
    if len(expected) <= 1 or expected.issubset(_declared[scene.id]):
        _resolve(scene.id)
    else:
        await _broadcast_waiting(db, scene, expected - _declared[scene.id])


async def note_skip(db: AsyncSession, scene: Scene, character_id: str) -> None:
    """A player declares they hold/skip this round."""
    _declared[scene.id].add(character_id)
    expected = await _participants(db, scene)
    if not expected or expected.issubset(_declared[scene.id]):
        _resolve(scene.id)
    else:
        await _broadcast_waiting(db, scene, expected - _declared[scene.id])


def resolve_now(scene_id: str) -> None:
    """DM forces the round to resolve, skipping anyone who hasn't declared."""
    _resolve(scene_id)


async def _broadcast_waiting(db: AsyncSession, scene: Scene, pending_ids: set[str]) -> None:
    names = list(
        (
            await db.execute(select(Character.name).where(Character.id.in_(pending_ids)))
        ).scalars()
    )
    label = ", ".join(sorted(names)) if names else "the party"
    hub.broadcast(
        scene.campaign_id,
        events.make_event(
            events.AI_STATUS,
            scene.campaign_id,
            {"status": f"Waiting for {label} to act… (DM can Resolve now)"},
            scene.id,
        ),
        scene_id=scene.id,
    )
