"""Opt-in real-model smoke test: one full AI-DM turn against a live
OpenAI-compatible endpoint. Skipped unless LLM_SMOKE=1 — CI never runs it.

Use it as a preflight check before a play session:

    make smoke-ollama
    # or, pointing anywhere:
    LLM_SMOKE=1 LLM_BASE_URL=http://localhost:11434/v1 LLM_MODEL=qwen3.6:35b-a3b \
        uv run pytest -q tests/test_smoke_ollama.py
"""

import asyncio
import os

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("LLM_SMOKE") != "1",
    reason="real-model smoke test — set LLM_SMOKE=1 with a model server running",
)


@pytest.fixture()
async def live_client(tmp_path, monkeypatch):
    """Like conftest.app_client, but against the real provider from the
    environment instead of the scripted mock. SRD prose ingestion is skipped —
    the turn under test doesn't need book search, and embedding the SRD against
    a live server would dominate the runtime."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "smoke-test-secret-key")
    monkeypatch.setenv("LLM_PROVIDER", "openai_compat")
    monkeypatch.setenv(
        "LLM_BASE_URL", os.environ.get("LLM_BASE_URL", "http://localhost:11434/v1")
    )
    monkeypatch.setenv("LLM_MODEL", os.environ.get("LLM_MODEL", "qwen3.6:35b-a3b"))
    monkeypatch.delenv("DATABASE_URL", raising=False)

    from app.config import get_settings

    get_settings.cache_clear()

    from app.ai.provider import set_provider
    from app.db import reset_engine

    set_provider(None)  # drop any cached provider so the env config loads fresh
    reset_engine()

    from app.main import _run_migrations_sync, create_app

    await asyncio.to_thread(_run_migrations_sync)

    from app.seed.load_srd import seed_srd

    await seed_srd()

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    set_provider(None)
    reset_engine()
    get_settings.cache_clear()


async def test_live_model_runs_a_turn(live_client):
    await live_client.post(
        "/api/v1/auth/register",
        json={"email": "dm@example.com", "password": "longenough", "display_name": "DM"},
    )
    campaign = (await live_client.post("/api/v1/campaigns", json={"name": "Smoke"})).json()
    scene = (
        await live_client.post(
            f"/api/v1/campaigns/{campaign['id']}/scenes",
            json={"name": "The Rusty Flagon", "kind": "main", "dm_mode": "ai"},
        )
    ).json()
    character = (
        await live_client.post(
            f"/api/v1/campaigns/{campaign['id']}/characters",
            json={
                "name": "Mira",
                "race": "elf",
                "subrace": "High Elf",
                "klass": "wizard",
                "background": "acolyte",
                "method": "standard",
                "base_scores": {"str": 8, "dex": 13, "con": 14, "int": 15, "wis": 12, "cha": 10},
                "skill_choices": ["arcana", "investigation"],
            },
        )
    ).json()

    await live_client.post(
        f"/api/v1/scenes/{scene['id']}/messages",
        json={
            "content": "I push open the tavern door and search the room for anything odd.",
            "character_id": character["id"],
        },
    )

    from app.ai.dm_agent import run_turn

    await run_turn(scene["id"])

    messages = (await live_client.get(f"/api/v1/scenes/{scene['id']}/messages")).json()
    narrations = [
        m for m in messages if m["author_type"] == "ai" and m["kind"] == "narration"
    ]
    assert narrations and narrations[-1]["content"].strip(), (
        "the live model produced no narration — check the server, model name, "
        "and that the model is fully downloaded"
    )

    # Loose expectation: tool use scales with model quality, so only report it.
    rolled = any(m["kind"] in ("roll", "tool_result") for m in messages)
    print(
        f"\nsmoke: narration OK ({len(narrations[-1]['content'])} chars); "
        f"tools used this turn: {'yes' if rolled else 'no'}"
    )
