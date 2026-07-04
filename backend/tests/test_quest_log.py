"""Quest-log endpoint: member access, DM-only twist notes."""

from .test_memory import setup_game


async def test_quest_log_hides_dm_notes_from_players(app_client):
    campaign, scene, _ = await setup_game(app_client)

    from app.db import get_sessionmaker
    from app.models import Quest

    async with get_sessionmaker()() as db:
        db.add(
            Quest(
                campaign_id=campaign["id"],
                title="Clear the watermill",
                status="active",
                summary="Rats in the mill. Allegedly.",
                objectives_json=[
                    {"text": "Reach the mill", "done": True},
                    {"text": "Deal with whatever is inside", "done": False},
                ],
                dm_notes="They are wererats.",
                created_by="ai",
            )
        )
        db.add(
            Quest(
                campaign_id=campaign["id"], title="Old rumor", status="completed",
                summary="Done and dusted.", created_by="dm",
            )
        )
        await db.commit()

    # DM (current session) sees the hidden twist.
    resp = await app_client.get(f"/api/v1/campaigns/{campaign['id']}/quests")
    assert resp.status_code == 200
    quests = resp.json()
    assert len(quests) == 2
    mill = next(q for q in quests if q["title"] == "Clear the watermill")
    assert mill["dm_notes"] == "They are wererats."
    assert mill["objectives_json"][0]["done"] is True

    # A player member sees the quest but not the twist.
    invite = campaign["invite_code"]
    await app_client.post(
        "/api/v1/auth/register",
        json={"email": "pl@example.com", "password": "longenough", "display_name": "PL"},
    )
    await app_client.post("/api/v1/campaigns/join", json={"invite_code": invite})
    resp = await app_client.get(f"/api/v1/campaigns/{campaign['id']}/quests")
    assert resp.status_code == 200
    mill = next(q for q in resp.json() if q["title"] == "Clear the watermill")
    assert "dm_notes" not in mill

    # Non-members are rejected.
    await app_client.post(
        "/api/v1/auth/register",
        json={"email": "rando@example.com", "password": "longenough", "display_name": "R"},
    )
    resp = await app_client.get(f"/api/v1/campaigns/{campaign['id']}/quests")
    assert resp.status_code in (401, 403)
