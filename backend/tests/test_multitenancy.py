"""Sharing one instance across groups: registration gating, per-campaign LLM
override, usage metering, and the token cap."""

from app.ai.mock_provider import MockProvider
from app.ai.provider import Done, LLMConfig, TextDelta, set_provider

from .test_memory import setup_game


def make_mock(script):
    mock = MockProvider(config=LLMConfig(provider="mock", toolcall_mode="native"))
    for turn in script:
        mock.queue_turn(turn)
    set_provider(mock)
    return mock


# --- Registration gating ---------------------------------------------------


async def _register(client, email, code=""):
    return await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "longenough", "display_name": email.split("@")[0],
              "invite_code": code},
    )


async def test_first_account_always_allowed_then_policy_applies(app_client):
    # Public endpoint reports the default before anyone configures it.
    assert (await app_client.get("/api/v1/auth/registration")).json()["mode"] == "open"

    # First account bootstraps (admin) even though we immediately lock signup.
    assert (await _register(app_client, "dm@example.com")).status_code == 200
    await app_client.put("/api/v1/admin/instance", json={"signup_mode": "closed"})

    # Now closed: a second signup is refused.
    assert (await app_client.get("/api/v1/auth/registration")).json()["mode"] == "closed"
    assert (await _register(app_client, "late@example.com")).status_code == 403


async def test_invite_mode_requires_matching_code(app_client):
    await _register(app_client, "dm@example.com")  # admin
    await app_client.put(
        "/api/v1/admin/instance",
        json={"signup_mode": "invite", "signup_code": "DRAGONS"},
    )

    assert (await _register(app_client, "nocode@example.com")).status_code == 403
    assert (await _register(app_client, "wrong@example.com", "nope")).status_code == 403
    assert (await _register(app_client, "right@example.com", "DRAGONS")).status_code == 200


async def test_instance_settings_are_admin_only(app_client):
    await _register(app_client, "dm@example.com")  # admin (first)
    await _register(app_client, "player@example.com")  # non-admin
    # (now logged in as the player via their session cookie)
    resp = await app_client.get("/api/v1/admin/instance")
    assert resp.status_code == 403


# --- Per-campaign LLM override ------------------------------------------------


async def test_campaign_llm_override_resolves_with_encrypted_key(app_client):
    campaign, _scene, _ = await setup_game(app_client)

    resp = await app_client.put(
        f"/api/v1/campaigns/{campaign['id']}/llm",
        json={"base_url": "https://opencode.ai/zen/go/v1", "model": "qwen3.6-plus",
              "api_key": "sk-group-secret", "token_cap": 50000},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["model"] == "qwen3.6-plus"
    assert body["api_key_set"] is True
    assert body["token_cap"] == 50000
    assert "sk-group-secret" not in str(body)  # never echoed back

    from app.db import get_sessionmaker
    from app.models import Campaign
    from app.services.settings_service import load_llm_config

    async with get_sessionmaker()() as db:
        row = await db.get(Campaign, campaign["id"])
        # Stored encrypted, not plaintext.
        assert row.settings_json["llm"]["api_key"] != "sk-group-secret"
        # …but load_llm_config decrypts and applies the whole override.
        cfg = await load_llm_config(row)
        assert cfg.model == "qwen3.6-plus"
        assert cfg.base_url == "https://opencode.ai/zen/go/v1"
        assert cfg.api_key == "sk-group-secret"

    # Clearing the key falls back to the shared default.
    await app_client.put(f"/api/v1/campaigns/{campaign['id']}/llm", json={"api_key": ""})
    assert (await app_client.get(f"/api/v1/campaigns/{campaign['id']}/llm")).json()[
        "api_key_set"
    ] is False


async def test_campaign_llm_is_dm_only(app_client):
    campaign, _scene, _ = await setup_game(app_client)
    invite = campaign["invite_code"]
    await app_client.post(
        "/api/v1/auth/register",
        json={"email": "pl@example.com", "password": "longenough", "display_name": "PL"},
    )
    await app_client.post("/api/v1/campaigns/join", json={"invite_code": invite})
    assert (await app_client.get(f"/api/v1/campaigns/{campaign['id']}/llm")).status_code == 403


# --- Usage meter + cap --------------------------------------------------------


async def _add_turn_usage(scene_id, prompt, completion):
    from app.db import get_sessionmaker
    from app.models import AiTurn

    async with get_sessionmaker()() as db:
        db.add(
            AiTurn(
                scene_id=scene_id, status="done",
                token_usage_json={"prompt_tokens": prompt, "completion_tokens": completion},
            )
        )
        await db.commit()


async def test_usage_meter_aggregates_turns(app_client):
    campaign, scene, _ = await setup_game(app_client)
    await _add_turn_usage(scene["id"], 1000, 300)
    await _add_turn_usage(scene["id"], 500, 200)

    usage = (await app_client.get(f"/api/v1/campaigns/{campaign['id']}/llm")).json()["usage"]
    assert usage == {
        "prompt_tokens": 1500,
        "completion_tokens": 500,
        "total_tokens": 2000,
        "turns": 2,
    }


async def test_token_cap_pauses_the_ai(app_client):
    campaign, scene, character = await setup_game(app_client)
    await _add_turn_usage(scene["id"], 9000, 2000)  # 11k already spent
    await app_client.put(f"/api/v1/campaigns/{campaign['id']}/llm", json={"token_cap": 10000})

    # Queue a narration the AI would give if it ran — it must NOT be consumed.
    mock = make_mock([[TextDelta("This should never be narrated."), Done()]])
    await app_client.post(
        f"/api/v1/scenes/{scene['id']}/messages",
        json={"content": "I look around.", "character_id": character["id"]},
    )
    from app.ai.dm_agent import run_turn

    await run_turn(scene["id"])

    assert mock.calls == []  # provider never invoked — capped before the loop
    msgs = (await app_client.get(f"/api/v1/scenes/{scene['id']}/messages")).json()
    assert not any(m["kind"] == "narration" for m in msgs)
    assert any("token cap" in m["content"].lower() for m in msgs)  # DM sees why
    set_provider(None)
