"""Runtime app settings: admin-UI values in app_settings override env defaults.

API keys are Fernet-encrypted with a key derived from SECRET_KEY.
"""

import base64
import hashlib
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select

from app.ai.provider import LLMConfig
from app.config import get_settings
from app.db import get_sessionmaker
from app.models import AppSetting

LLM_SETTINGS_KEY = "llm"
SECRET_FIELDS = {"api_key", "embedding_api_key"}


def _fernet() -> Fernet:
    digest = hashlib.sha256(get_settings().secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode()).decode()
    except (InvalidToken, ValueError):
        return ""


async def get_setting(key: str) -> dict[str, Any]:
    async with get_sessionmaker()() as db:
        result = await db.execute(select(AppSetting).where(AppSetting.key == key))
        row = result.scalar_one_or_none()
        return dict(row.value_json) if row else {}


async def put_setting(key: str, value: dict[str, Any]) -> None:
    async with get_sessionmaker()() as db:
        result = await db.execute(select(AppSetting).where(AppSetting.key == key))
        row = result.scalar_one_or_none()
        if row:
            row.value_json = value
        else:
            db.add(AppSetting(key=key, value_json=value))
        await db.commit()


async def load_llm_config(campaign: Any = None) -> LLMConfig:
    """Env defaults, overridden by admin-saved values, then (if given) by a
    campaign's own LLM overrides — so a group can bring its own model/key."""
    env = get_settings()
    config = LLMConfig(
        provider=env.llm_provider,
        base_url=env.llm_base_url,
        api_key=env.llm_api_key,
        model=env.llm_model,
        toolcall_mode=env.llm_toolcall_mode,
        embedding_base_url=env.embedding_base_url,
        embedding_api_key=env.embedding_api_key,
        embedding_model=env.embedding_model,
    )
    stored = await get_setting(LLM_SETTINGS_KEY)
    for field_name in (
        "provider",
        "base_url",
        "model",
        "toolcall_mode",
        "embedding_base_url",
        "embedding_model",
        "temperature",
        "max_tokens",
    ):
        if field_name in stored and stored[field_name] not in (None, ""):
            setattr(config, field_name, stored[field_name])
    for secret in SECRET_FIELDS:
        if stored.get(secret):
            decrypted = decrypt_secret(stored[secret])
            if decrypted:
                setattr(config, secret, decrypted)

    # Per-campaign overrides (chat side only — embeddings/RAG stay on the shared
    # index). api_key is Fernet-encrypted in the campaign's settings_json.
    overrides = ((getattr(campaign, "settings_json", None) or {}).get("llm")) or {}
    for field_name in ("base_url", "model", "toolcall_mode"):
        if overrides.get(field_name):
            setattr(config, field_name, overrides[field_name])
    if overrides.get("api_key"):
        decrypted = decrypt_secret(overrides["api_key"])
        if decrypted:
            config.api_key = decrypted
    return config


async def save_llm_config(values: dict[str, Any]) -> None:
    stored = await get_setting(LLM_SETTINGS_KEY)
    for key, value in values.items():
        if value is None:
            continue
        if key in SECRET_FIELDS:
            if value == "":
                stored.pop(key, None)  # empty string clears back to env default
            else:
                stored[key] = encrypt_secret(value)
        else:
            stored[key] = value
    await put_setting(LLM_SETTINGS_KEY, stored)

    from app.ai.provider import set_provider

    set_provider(None)  # rebuild on next use
