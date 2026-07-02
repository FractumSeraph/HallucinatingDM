import asyncio

import httpx
import pytest


@pytest.fixture()
async def app_client(tmp_path, monkeypatch):
    """Fresh app + migrated tmp SQLite per test. Lifespan is bypassed (ASGITransport
    doesn't run it), so migrations are applied explicitly — which also keeps the
    migration chain continuously tested."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    from app.config import get_settings

    get_settings.cache_clear()

    from app.db import reset_engine

    reset_engine()

    from app.main import _run_migrations_sync, create_app

    await asyncio.to_thread(_run_migrations_sync)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        client.app = app  # type: ignore[attr-defined]
        yield client

    reset_engine()
    get_settings.cache_clear()
