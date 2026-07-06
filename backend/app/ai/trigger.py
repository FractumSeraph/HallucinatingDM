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
    if message.author_type == "player" and message.kind == "chat" and message.character_id and db:
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
    """Active player characters taking part in this scene (its roster)."""
    ids = list(scene.party_json or [])
    if not ids:
        return set()
    rows = (
        await db.execute(
            select(Character.id).where(Character.id.in_(ids), Character.status == "active")
        )
    ).scalars()
    return set(rows)


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
