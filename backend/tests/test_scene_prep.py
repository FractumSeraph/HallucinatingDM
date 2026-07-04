"""DM scene prep: read secret notes, set notes + bind a prepped location."""

from .test_memory import setup_game


async def test_scene_prep_read_and_update(app_client):
    campaign, scene, _ = await setup_game(app_client)

    # A place prepped ahead of time, with a secret twist.
    loc = (
        await app_client.post(
            f"/api/v1/campaigns/{campaign['id']}/world/location",
            json={"fields": {"name": "The Old Mill", "kind": "building",
                             "description": "A derelict watermill.",
                             "dm_notes": "Wererats nest in the cellar."}},
        )
    ).json()

    # Prep starts empty and is DM-only readable.
    prep = (await app_client.get(f"/api/v1/scenes/{scene['id']}/prep")).json()
    assert prep == {"dm_notes": "", "time_note": "", "location_id": None}

    # Set secret notes, a time, and bind the prepped location.
    resp = await app_client.patch(
        f"/api/v1/scenes/{scene['id']}",
        json={"dm_notes": "The mill door is barred from inside.",
              "time_note": "dusk", "location_id": loc["id"]},
    )
    assert resp.status_code == 200
    assert resp.json()["location_id"] == loc["id"]  # SceneOut reflects the binding

    prep = (await app_client.get(f"/api/v1/scenes/{scene['id']}/prep")).json()
    assert prep["dm_notes"] == "The mill door is barred from inside."
    assert prep["time_note"] == "dusk"
    assert prep["location_id"] == loc["id"]

    # Empty string clears the location.
    await app_client.patch(f"/api/v1/scenes/{scene['id']}", json={"location_id": ""})
    prep = (await app_client.get(f"/api/v1/scenes/{scene['id']}/prep")).json()
    assert prep["location_id"] is None


async def test_scene_prep_is_dm_only(app_client):
    campaign, scene, _ = await setup_game(app_client)
    invite = campaign["invite_code"]
    await app_client.post(
        "/api/v1/auth/register",
        json={"email": "pl@example.com", "password": "longenough", "display_name": "PL"},
    )
    await app_client.post("/api/v1/campaigns/join", json={"invite_code": invite})

    # A player member cannot read the secret prep.
    resp = await app_client.get(f"/api/v1/scenes/{scene['id']}/prep")
    assert resp.status_code == 403


async def test_scene_location_rejects_foreign_id(app_client):
    campaign, scene, _ = await setup_game(app_client)
    resp = await app_client.patch(
        f"/api/v1/scenes/{scene['id']}", json={"location_id": "not-a-real-location"}
    )
    assert resp.status_code == 400


async def test_prepped_location_notes_reach_the_prompt_when_bound(app_client):
    """The end-to-end payoff: bind a prepped location to a scene and its secret
    notes appear in the AI's system prompt for that scene."""
    from app.ai.mock_provider import MockProvider
    from app.ai.provider import Done, LLMConfig, TextDelta, set_provider

    campaign, scene, _ = await setup_game(app_client)
    loc = (
        await app_client.post(
            f"/api/v1/campaigns/{campaign['id']}/world/location",
            json={"fields": {"name": "The Old Mill", "description": "A derelict watermill.",
                             "dm_notes": "Wererats nest in the cellar."}},
        )
    ).json()
    await app_client.patch(f"/api/v1/scenes/{scene['id']}", json={"location_id": loc["id"]})

    mock = MockProvider(config=LLMConfig(provider="mock", toolcall_mode="native"))
    mock.queue_turn([TextDelta("The mill looms."), Done()])
    set_provider(mock)
    from app.ai.dm_agent import run_turn

    await run_turn(scene["id"])
    system = mock.calls[0].messages[0]["content"]
    assert "The Old Mill" in system
    assert "Wererats nest in the cellar" in system  # secret notes injected for the DM/AI
    set_provider(None)
