"""Multiplayer turn-gathering: the AI waits for every participant to declare
before resolving; players can Skip and the DM can force-resolve."""

import app.ai.trigger as trig
from app.models import Message


def _msg(scene_id, character_id, kind="chat", author_type="player"):
    return Message(
        scene_id=scene_id, seq=1, author_type=author_type, kind=kind,
        content="I act", character_id=character_id,
    )


async def _scene_with_party(app_client, party_size):
    """DM + AI scene + `party_size` active characters, all in the roster."""
    me = (
        await app_client.post(
            "/api/v1/auth/register",
            json={"email": "dm@example.com", "password": "longenough", "display_name": "DM"},
        )
    ).json()
    uid = me["id"]
    campaign = (await app_client.post("/api/v1/campaigns", json={"name": "C"})).json()
    scene = (
        await app_client.post(
            f"/api/v1/campaigns/{campaign['id']}/scenes",
            json={"name": "Fight", "kind": "main", "dm_mode": "ai"},
        )
    ).json()

    from app.db import get_sessionmaker
    from app.models import Character, Scene

    ids = []
    async with get_sessionmaker()() as db:
        for i in range(party_size):
            c = Character(
                campaign_id=campaign["id"], user_id=uid, name=f"PC{i}",
                race="human", klass="fighter", level=1, hp_current=10, hp_max=10, ac=12,
                status="active",
            )
            db.add(c)
            await db.flush()
            ids.append(c.id)
        s = await db.get(Scene, scene["id"])
        s.party_json = list(ids)
        await db.commit()
    return campaign, scene["id"], ids


async def test_solo_scene_resolves_immediately(app_client, monkeypatch):
    trig._declared.clear()
    fired: list[str] = []
    monkeypatch.setattr("app.ai.dm_agent.trigger_turn", lambda sid: fired.append(sid))

    _campaign, sid, ids = await _scene_with_party(app_client, 1)
    from app.db import get_sessionmaker
    from app.models import Scene

    async with get_sessionmaker()() as db:
        scene = await db.get(Scene, sid)
        await trig.maybe_trigger_ai_turn(scene, _msg(sid, ids[0]), db)
    assert fired == [sid]  # one participant → fires at once


async def test_multiplayer_waits_for_all_then_resolves(app_client, monkeypatch):
    trig._declared.clear()
    fired: list[str] = []
    monkeypatch.setattr("app.ai.dm_agent.trigger_turn", lambda sid: fired.append(sid))

    _campaign, sid, ids = await _scene_with_party(app_client, 2)
    from app.db import get_sessionmaker
    from app.models import Scene

    async with get_sessionmaker()() as db:
        scene = await db.get(Scene, sid)
        # First player declares — the AI must NOT act yet.
        await trig.maybe_trigger_ai_turn(scene, _msg(sid, ids[0]), db)
        assert fired == []
        # Second player declares — now the round resolves.
        await trig.maybe_trigger_ai_turn(scene, _msg(sid, ids[1]), db)
        assert fired == [sid]


async def test_skip_lets_the_round_resolve(app_client, monkeypatch):
    trig._declared.clear()
    fired: list[str] = []
    monkeypatch.setattr("app.ai.dm_agent.trigger_turn", lambda sid: fired.append(sid))

    _campaign, sid, ids = await _scene_with_party(app_client, 2)
    from app.db import get_sessionmaker
    from app.models import Scene

    async with get_sessionmaker()() as db:
        scene = await db.get(Scene, sid)
        await trig.maybe_trigger_ai_turn(scene, _msg(sid, ids[0]), db)
        assert fired == []
        await trig.note_skip(db, scene, ids[1])  # the other player holds
        assert fired == [sid]


async def test_dm_resolve_now_forces_the_round(app_client, monkeypatch):
    trig._declared.clear()
    fired: list[str] = []
    monkeypatch.setattr("app.ai.dm_agent.trigger_turn", lambda sid: fired.append(sid))

    _campaign, sid, ids = await _scene_with_party(app_client, 2)
    from app.db import get_sessionmaker
    from app.models import Scene

    async with get_sessionmaker()() as db:
        scene = await db.get(Scene, sid)
        await trig.maybe_trigger_ai_turn(scene, _msg(sid, ids[0]), db)
        assert fired == []
    trig.resolve_now(sid)  # DM clicks Resolve while PC1 is still AFK
    assert fired == [sid]


async def test_combat_bypasses_gathering(app_client, monkeypatch):
    """During combat, initiative decides who acts — the acting player's message
    resolves immediately instead of waiting on the rest of the party."""
    trig._declared.clear()
    fired: list[str] = []
    monkeypatch.setattr("app.ai.dm_agent.trigger_turn", lambda sid: fired.append(sid))

    _campaign, sid, ids = await _scene_with_party(app_client, 3)
    from app.db import get_sessionmaker
    from app.models import Scene
    from app.services import combat as combat_service

    async with get_sessionmaker()() as db:
        scene = await db.get(Scene, sid)
        await combat_service.start_encounter(db, scene, ["PC0", "wolf"])
        fired.clear()
        await trig.maybe_trigger_ai_turn(scene, _msg(sid, ids[0]), db)
    assert fired == [sid]  # no waiting on PC1/PC2 — initiative rules combat


async def test_unconscious_character_does_not_block_the_round(app_client, monkeypatch):
    trig._declared.clear()
    fired: list[str] = []
    monkeypatch.setattr("app.ai.dm_agent.trigger_turn", lambda sid: fired.append(sid))

    _campaign, sid, ids = await _scene_with_party(app_client, 2)
    from app.db import get_sessionmaker
    from app.models import Character, Scene

    async with get_sessionmaker()() as db:
        downed = await db.get(Character, ids[1])
        downed.hp_current = 0  # dying — they cannot declare an action
        await db.commit()
        scene = await db.get(Scene, sid)
        await trig.maybe_trigger_ai_turn(scene, _msg(sid, ids[0]), db)
    assert fired == [sid]  # only conscious PC0 was expected


async def test_dm_message_resolves_without_waiting(app_client, monkeypatch):
    trig._declared.clear()
    fired: list[str] = []
    monkeypatch.setattr("app.ai.dm_agent.trigger_turn", lambda sid: fired.append(sid))

    _campaign, sid, ids = await _scene_with_party(app_client, 2)
    from app.db import get_sessionmaker
    from app.models import Scene

    async with get_sessionmaker()() as db:
        scene = await db.get(Scene, sid)
        # DM speaking is direction, not a player declaration — resolve at once.
        await trig.maybe_trigger_ai_turn(scene, _msg(sid, None, author_type="dm"), db)
    assert fired == [sid]


async def test_characterless_chat_does_not_cut_the_round_short(app_client, monkeypatch):
    """A player with no character can't act — their chat is table talk while a
    party is mid-round, not a trigger that resolves everyone else's turn."""
    trig._declared.clear()
    fired: list[str] = []
    monkeypatch.setattr("app.ai.dm_agent.trigger_turn", lambda sid: fired.append(sid))

    _campaign, sid, ids = await _scene_with_party(app_client, 2)
    from app.db import get_sessionmaker
    from app.models import Scene

    async with get_sessionmaker()() as db:
        scene = await db.get(Scene, sid)
        # PC0 declares; the round now waits on PC1…
        await trig.maybe_trigger_ai_turn(scene, _msg(sid, ids[0]), db)
        assert fired == []
        # …and a characterless spectator message must NOT resolve it.
        await trig.maybe_trigger_ai_turn(scene, _msg(sid, None), db)
        assert fired == []
        # PC1 declares → now it resolves.
        await trig.maybe_trigger_ai_turn(scene, _msg(sid, ids[1]), db)
        assert fired == [sid]
