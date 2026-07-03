"""Embedding helpers: nomic task prefixes, dimension bookkeeping, vec0 table."""

import logging
import struct

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.provider import get_provider
from app.models import EmbeddingConfig

log = logging.getLogger("hallucinatingdm.rag")

BATCH_SIZE = 32


def _needs_prefix(model: str) -> bool:
    return "nomic" in model.lower()


def serialize_f32(vector: list[float]) -> bytes:
    return struct.pack(f"{len(vector)}f", *vector)


async def embed_documents(texts: list[str]) -> list[list[float]]:
    provider = await get_provider()
    prefix = "search_document: " if _needs_prefix(provider.config.embedding_model) else ""
    out: list[list[float]] = []
    for i in range(0, len(texts), BATCH_SIZE):
        batch = [prefix + t for t in texts[i : i + BATCH_SIZE]]
        out.extend(await provider.embed(batch))
    return out


async def embed_query(query: str) -> list[float]:
    provider = await get_provider()
    prefix = "search_query: " if _needs_prefix(provider.config.embedding_model) else ""
    vectors = await provider.embed([prefix + query])
    return vectors[0]


async def get_embedding_config(db: AsyncSession) -> EmbeddingConfig | None:
    return (await db.execute(select(EmbeddingConfig))).scalars().first()


async def ensure_vec_table(db: AsyncSession, dim: int) -> bool:
    """Create chunks_vec (and record the model/dim) if compatible; returns
    False when the stored index was built by a different model/dimension."""
    from app.db import vec_available

    if not vec_available:
        return False
    provider = await get_provider()
    config = await get_embedding_config(db)
    if config is None:
        db.add(EmbeddingConfig(model=provider.config.embedding_model, dim=dim))
        await db.commit()
    elif config.dim != dim or config.model != provider.config.embedding_model:
        log.warning(
            "embedding config mismatch (stored %s/%d, current %s/%d) — reindex required",
            config.model, config.dim, provider.config.embedding_model, dim,
        )
        return False
    await db.execute(
        text(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS chunks_vec USING vec0("
            f"chunk_id TEXT PRIMARY KEY, embedding float[{dim}])"
        )
    )
    await db.commit()
    return True


async def store_vectors(db: AsyncSession, ids_and_vectors: list[tuple[str, list[float]]]) -> bool:
    if not ids_and_vectors:
        return True
    ok = await ensure_vec_table(db, len(ids_and_vectors[0][1]))
    if not ok:
        return False
    for chunk_id, vector in ids_and_vectors:
        await db.execute(
            text("DELETE FROM chunks_vec WHERE chunk_id = :cid"), {"cid": chunk_id}
        )
        await db.execute(
            text("INSERT INTO chunks_vec(chunk_id, embedding) VALUES (:cid, :vec)"),
            {"cid": chunk_id, "vec": serialize_f32(vector)},
        )
    await db.commit()
    return True
