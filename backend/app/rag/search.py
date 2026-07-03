"""Hybrid retrieval: sqlite-vec KNN + FTS5, fused with reciprocal rank fusion.

FTS carries keyword-heavy rules queries ("grappled condition") and keeps
quality decent when embeddings are unavailable or weak; vectors add semantic
recall. Either side can be empty — the other still works.
"""

import logging
import re
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chunk, Document
from app.rag.embedder import embed_query, get_embedding_config, serialize_f32

log = logging.getLogger("hallucinatingdm.rag")

CANDIDATES = 20
RRF_K = 60


@dataclass
class SearchHit:
    chunk_id: str
    text: str
    section_path: str
    page_start: int
    page_end: int
    document_title: str
    score: float


def _fts_query(raw: str) -> str:
    """Quote terms so user input can't break FTS5 syntax."""
    terms = re.findall(r"[A-Za-z0-9]+", raw)
    return " ".join(f'"{t}"' for t in terms[:12])


async def _fts_candidates(db: AsyncSession, query: str) -> list[tuple[str, int]]:
    fts = _fts_query(query)
    if not fts:
        return []
    rows = await db.execute(
        text(
            "SELECT c.id, rank FROM chunks_fts f JOIN chunks c ON c.rowid = f.rowid "
            "WHERE chunks_fts MATCH :q ORDER BY rank LIMIT :n"
        ),
        {"q": fts, "n": CANDIDATES},
    )
    return [(row[0], i) for i, row in enumerate(rows.fetchall())]


async def _vector_candidates(db: AsyncSession, query: str) -> list[tuple[str, int]]:
    from app.db import vec_available

    if not vec_available:
        return []
    config = await get_embedding_config(db)
    if config is None:
        return []
    exists = await db.execute(
        text("SELECT name FROM sqlite_master WHERE name = 'chunks_vec'")
    )
    if not exists.first():
        return []
    try:
        vector = await embed_query(query)
    except Exception as exc:
        log.debug("query embedding unavailable: %s", exc)
        return []
    if len(vector) != config.dim:
        log.warning("embedding dim mismatch (%d vs %d) — reindex required", len(vector), config.dim)
        return []
    rows = await db.execute(
        text(
            "SELECT chunk_id, distance FROM chunks_vec "
            "WHERE embedding MATCH :vec AND k = :n ORDER BY distance"
        ),
        {"vec": serialize_f32(vector), "n": CANDIDATES},
    )
    return [(row[0], i) for i, row in enumerate(rows.fetchall())]


async def search_books(
    db: AsyncSession, campaign_id: str | None, query: str, limit: int = 6
) -> list[SearchHit]:
    fts = await _fts_candidates(db, query)
    vec = await _vector_candidates(db, query)

    scores: dict[str, float] = {}
    for chunk_id, rank in fts:
        scores[chunk_id] = scores.get(chunk_id, 0) + 1 / (RRF_K + rank)
    for chunk_id, rank in vec:
        scores[chunk_id] = scores.get(chunk_id, 0) + 1 / (RRF_K + rank)
    if not scores:
        return []

    ranked_ids = sorted(scores, key=lambda cid: scores[cid], reverse=True)
    rows = await db.execute(
        select(Chunk, Document)
        .join(Document, Document.id == Chunk.document_id)
        .where(Chunk.id.in_(ranked_ids))
    )
    by_id = {
        chunk.id: (chunk, doc)
        for chunk, doc in rows.all()
        # global docs (SRD) + this campaign's uploads only
        if doc.campaign_id is None or doc.campaign_id == campaign_id
    }
    hits = []
    for chunk_id in ranked_ids:
        if chunk_id not in by_id:
            continue
        chunk, doc = by_id[chunk_id]
        hits.append(
            SearchHit(
                chunk_id=chunk.id,
                text=chunk.text,
                section_path=chunk.section_path,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                document_title=doc.title,
                score=round(scores[chunk_id], 5),
            )
        )
        if len(hits) >= limit:
            break
    return hits
