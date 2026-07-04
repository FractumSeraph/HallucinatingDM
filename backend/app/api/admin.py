from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import CurrentUser, DbSession
from app.api.errors import forbidden
from app.services.settings_service import (
    get_setting,
    load_llm_config,
    put_setting,
    save_llm_config,
)

router = APIRouter(prefix="/admin", tags=["admin"])

INSTANCE_SETTINGS_KEY = "instance"


class LlmSettingsPatch(BaseModel):
    provider: str | None = None
    base_url: str | None = None
    api_key: str | None = None  # "" clears back to env default
    model: str | None = None
    toolcall_mode: str | None = None
    embedding_base_url: str | None = None
    embedding_api_key: str | None = None
    embedding_model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None


def _require_admin(user) -> None:
    if not user.is_admin:
        raise forbidden("Admin access required")


@router.get("/settings")
async def get_llm_settings(user: CurrentUser, _db: DbSession) -> dict[str, Any]:
    _require_admin(user)
    config = await load_llm_config()
    stored = await get_setting("llm")
    return {
        "provider": config.provider,
        "llm_base_url": config.base_url,
        "llm_model": config.model,
        "llm_api_key_set": bool(stored.get("api_key")),
        "llm_toolcall_mode": config.toolcall_mode,
        "embedding_base_url": config.embedding_base_url,
        "embedding_model": config.embedding_model,
        "embedding_api_key_set": bool(stored.get("embedding_api_key")),
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
    }


@router.put("/settings")
async def put_llm_settings(
    body: LlmSettingsPatch, user: CurrentUser, _db: DbSession
) -> dict[str, Any]:
    _require_admin(user)
    values = body.model_dump(exclude_none=True)
    # map API field names to stored names
    renames = {
        "base_url": "base_url",
        "api_key": "api_key",
        "model": "model",
    }
    stored_values = {renames.get(k, k): v for k, v in values.items()}
    await save_llm_config(stored_values)
    return await get_llm_settings(user, _db)


class InstancePatch(BaseModel):
    signup_mode: str | None = None  # open | invite | closed
    signup_code: str | None = None


@router.get("/instance")
async def get_instance_settings(user: CurrentUser, _db: DbSession) -> dict[str, Any]:
    _require_admin(user)
    instance = await get_setting(INSTANCE_SETTINGS_KEY)
    return {
        "signup_mode": instance.get("signup_mode", "open"),
        "signup_code": instance.get("signup_code", ""),
    }


@router.put("/instance")
async def put_instance_settings(
    body: InstancePatch, user: CurrentUser, _db: DbSession
) -> dict[str, Any]:
    _require_admin(user)
    instance = await get_setting(INSTANCE_SETTINGS_KEY)
    if body.signup_mode is not None:
        if body.signup_mode not in ("open", "invite", "closed"):
            raise forbidden("Invalid signup mode")
        instance["signup_mode"] = body.signup_mode
    if body.signup_code is not None:
        instance["signup_code"] = body.signup_code.strip()
    await put_setting(INSTANCE_SETTINGS_KEY, instance)
    return await get_instance_settings(user, _db)


@router.post("/reindex")
async def reindex(user: CurrentUser, _db: DbSession) -> dict[str, Any]:
    """Rebuild all chunk embeddings with the currently configured model."""
    _require_admin(user)
    from app.rag.ingest import reindex_embeddings

    try:
        return await reindex_embeddings()
    except Exception as exc:
        return {"error": str(exc)[:300]}


@router.post("/settings/test-llm")
async def test_llm(user: CurrentUser, _db: DbSession) -> dict[str, Any]:
    """Round-trip a hello + an embedding to validate the configuration."""
    _require_admin(user)
    from app.ai.provider import Done, TextDelta, get_provider, set_provider

    set_provider(None)  # pick up latest settings
    provider = await get_provider()
    report: dict[str, Any] = {
        "model": provider.config.model,
        "base_url": provider.config.base_url,
    }
    try:
        text = ""
        async for event in provider.chat(
            [{"role": "user", "content": "Reply with exactly: READY"}],
            max_tokens=20,
        ):
            if isinstance(event, TextDelta):
                text += event.text
            elif isinstance(event, Done):
                pass
        report["chat_ok"] = True
        report["chat_reply"] = text.strip()[:100]
    except Exception as exc:
        report["chat_ok"] = False
        report["chat_error"] = str(exc)[:300]

    try:
        vectors = await provider.embed(["hello world"])
        report["embedding_ok"] = True
        report["embedding_dim"] = len(vectors[0]) if vectors else 0
    except Exception as exc:
        report["embedding_ok"] = False
        report["embedding_error"] = str(exc)[:300]

    return report
