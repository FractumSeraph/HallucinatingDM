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
