"""Automatic per-turn memory retrieval for the AI DM.

Small local models rarely think to call recall_lore, so every turn the context
builder runs a cheap keyword search over the campaign's long-term stores —
world events, chat older than the transcript window, and named entities — and
injects the top hits into the prompt. recall_lore remains for explicit deep
searches.
"""

import logging
import re

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import NPC, Faction, Location, Quest

log = logging.getLogger("hallucinatingdm.retrieval")

MAX_SNIPPETS = 6
SNIPPET_CHARS = 240

_STOPWORDS = frozenset(
    "the and for with that this from what who where when how did does about "
    "you your our are was were have has had they them then than into out not "
    "can will would could should say says said ask asks tell tells".split()
)


def _fts_or_query(raw: str) -> str:
    """Quote terms so chat text can't break FTS5 syntax; OR them so any strong
    keyword can hit — bm25 rank puts the rare (interesting) matches first."""
    terms = [
        t for t in re.findall(r"[A-Za-z0-9]+", raw) if len(t) > 2 and t.lower() not in _STOPWORDS
    ]
    return " OR ".join(f'"{t}"' for t in terms[:12])


async def auto_recall(
    db: AsyncSession,
    campaign_id: str,
    scene_id: str,
    query: str,
    exclude_scene_after_seq: int = 0,
) -> list[str]:
    """Top snippets from the campaign's past, tagged with provenance.

    Current-scene messages newer than exclude_scene_after_seq are skipped —
    they're already in the transcript the model sees.
    """
    snippets: list[str] = []
    fts = _fts_or_query(query)

    if fts:
        try:
            rows = await db.execute(
                text(
                    "SELECT w.description FROM world_events_fts f "
                    "JOIN world_events w ON w.rowid = f.rowid "
                    "WHERE world_events_fts MATCH :q AND w.campaign_id = :cid "
                    "ORDER BY rank LIMIT 3"
                ),
                {"q": fts, "cid": campaign_id},
            )
            snippets.extend(f"[event] {r[0][:SNIPPET_CHARS]}" for r in rows.fetchall())
        except Exception as exc:
            log.debug("world-event recall unavailable: %s", exc)
        try:
            rows = await db.execute(
                text(
                    "SELECT m.content FROM messages_fts f "
                    "JOIN messages m ON m.rowid = f.rowid "
                    "JOIN scenes s ON s.id = m.scene_id "
                    "WHERE messages_fts MATCH :q AND s.campaign_id = :cid "
                    "AND m.visibility = 'all' AND m.struck = 0 "
                    "AND m.author_type IN ('player', 'dm', 'ai') "
                    "AND (m.scene_id != :sid OR m.seq <= :cutoff) "
                    "ORDER BY rank LIMIT 3"
                ),
                {
                    "q": fts,
                    "cid": campaign_id,
                    "sid": scene_id,
                    "cutoff": exclude_scene_after_seq,
                },
            )
            snippets.extend(f"[said earlier] {r[0][:SNIPPET_CHARS]}" for r in rows.fetchall())
        except Exception as exc:
            log.debug("message recall unavailable: %s", exc)

    # Exact/substring entity-name matches (same approach as recall_lore).
    terms = {t.lower() for t in re.findall(r"[A-Za-z0-9]+", query) if len(t) > 3}
    lowered = query.lower()
    for model, kind, fields in (
        (NPC, "npc", ("role", "disposition", "description")),
        (Location, "location", ("kind", "description")),
        (Faction, "faction", ("description", "goals")),
        (Quest, "quest", ("status", "summary")),
    ):
        rows = list(
            (await db.execute(select(model).where(model.campaign_id == campaign_id))).scalars()
        )
        for row in rows:
            name = getattr(row, "title", None) or getattr(row, "name", "")
            name_l = name.lower()
            if name and (name_l in lowered or any(t in name_l for t in terms)):
                detail = "; ".join(
                    f"{f}: {getattr(row, f)}" for f in fields if getattr(row, f, "")
                )
                snippets.append(f"[{kind}] {name} — {detail[:SNIPPET_CHARS]}")

    seen: set[str] = set()
    out: list[str] = []
    for snippet in snippets:
        if snippet in seen:
            continue
        seen.add(snippet)
        out.append(snippet)
        if len(out) >= MAX_SNIPPETS:
            break
    return out
