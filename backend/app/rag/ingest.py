"""PDF → text → chunks → embeddings, run as a background task after upload."""

import asyncio
import logging
import statistics
from pathlib import Path

from sqlalchemy import delete, select

from app.db import get_sessionmaker
from app.models import Chunk, Document, SrdEntry
from app.rag.chunker import PageText, chunk_pages
from app.rag.embedder import embed_documents, store_vectors
from app.realtime import events
from app.realtime.hub import hub

log = logging.getLogger("hallucinatingdm.rag")


def extract_pdf_pages(path: Path) -> list[PageText]:
    """PyMuPDF extraction with a font-size heading heuristic."""
    import fitz  # PyMuPDF

    pages: list[PageText] = []
    with fitz.open(path) as doc:
        # First pass: find the dominant body font size.
        sizes: list[float] = []
        for page in doc:
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        if span["text"].strip():
                            sizes.append(round(span["size"], 1))
        body_size = statistics.median(sizes) if sizes else 11.0
        heading_cutoff = body_size * 1.25

        for page_no, page in enumerate(doc, start=1):
            headings: list[str] = []
            paragraphs: list[str] = []
            for block in page.get_text("dict")["blocks"]:
                block_lines: list[str] = []
                block_max_size = 0.0
                for line in block.get("lines", []):
                    line_text = "".join(s["text"] for s in line.get("spans", [])).strip()
                    if not line_text:
                        continue
                    block_lines.append(line_text)
                    block_max_size = max(
                        block_max_size,
                        max((s["size"] for s in line.get("spans", [])), default=0),
                    )
                if not block_lines:
                    continue
                block_text = " ".join(block_lines).strip()
                if (
                    block_max_size >= heading_cutoff
                    and len(block_text) < 90
                    and block_text[-1:] not in ".!?,;"
                ):
                    headings.append(block_text)
                paragraphs.append(block_text)
            pages.append(
                PageText(page=page_no, text="\n\n".join(paragraphs), headings=headings)
            )
    return pages


def _progress(document: Document, pct: int) -> None:
    hub.broadcast(
        document.campaign_id or "",
        events.make_event(
            events.DOCUMENT_PROGRESS,
            document.campaign_id or "",
            {"document_id": document.id, "status": document.status, "progress": pct},
        ),
    ) if document.campaign_id else None


async def ingest_document(document_id: str, pdf_path: str) -> None:
    async with get_sessionmaker()() as db:
        document = await db.get(Document, document_id)
        if not document:
            return
        try:
            pages = await asyncio.to_thread(extract_pdf_pages, Path(pdf_path))
            document.page_count = len(pages)
            document.progress = 20
            await db.commit()
            _progress(document, 20)

            chunks = chunk_pages(pages)
            title = document.title
            rows = [
                Chunk(
                    document_id=document.id,
                    chunk_index=i,
                    page_start=c.page_start,
                    page_end=c.page_end,
                    section_path=(f"{title} > {c.section_path}" if c.section_path else title),
                    text=c.text,
                )
                for i, c in enumerate(chunks)
            ]
            db.add_all(rows)
            document.chunk_count = len(rows)
            document.progress = 50
            await db.commit()
            _progress(document, 50)

            # Embeddings are best-effort: FTS works even when the embedding
            # server is down; vectors can be built later via admin reindex.
            try:
                vectors = await embed_documents([r.text for r in rows])
                await store_vectors(db, [(r.id, v) for r, v in zip(rows, vectors, strict=True)])
            except Exception as exc:
                log.warning("embedding failed for %s (FTS-only): %s", document.title, exc)

            document.status = "ready"
            document.progress = 100
            await db.commit()
            _progress(document, 100)
        except Exception as exc:
            log.exception("ingest failed for document %s", document_id)
            document.status = "error"
            document.error = str(exc)[:2000]
            await db.commit()
            _progress(document, 100)


SRD_DOC_TITLE = "SRD 5.1 — Rules Reference"


async def ingest_srd_prose() -> None:
    """Boot-time: put SRD rule/condition prose through the chunk store so rules
    search works before anyone uploads a book. No embeddings at boot (the LLM
    server may not be up); admin reindex or the first search backfills them."""
    async with get_sessionmaker()() as db:
        existing = (
            await db.execute(select(Document).where(Document.title == SRD_DOC_TITLE))
        ).scalars().first()
        if existing:
            return
        document = Document(
            campaign_id=None, title=SRD_DOC_TITLE, filename="", status="ready"
        )
        db.add(document)
        await db.flush()

        entries = list(
            (
                await db.execute(
                    select(SrdEntry).where(SrdEntry.kind.in_(["rule", "condition"]))
                )
            ).scalars()
        )
        index = 0
        for entry in entries:
            body = str(entry.data_json.get("description", "")).strip()
            if not body:
                continue
            section = entry.data_json.get("section") or entry.kind.title()
            # Split long rules into ~3200-char paragraph groups
            paragraphs = [p for p in body.split("\n\n") if p.strip()]
            buffer: list[str] = []
            size = 0
            parts: list[str] = []
            for para in paragraphs:
                buffer.append(para)
                size += len(para)
                if size >= 3200:
                    parts.append("\n\n".join(buffer))
                    buffer, size = [], 0
            if buffer:
                parts.append("\n\n".join(buffer))
            for part in parts:
                db.add(
                    Chunk(
                        document_id=document.id,
                        chunk_index=index,
                        section_path=f"SRD 5.1 > {section} > {entry.name}",
                        text=part,
                    )
                )
                index += 1
        document.chunk_count = index
        await db.commit()


async def reindex_embeddings() -> dict:
    """Re-embed every chunk with the currently configured embedding model."""
    from sqlalchemy import text as sql_text

    from app.models import EmbeddingConfig

    async with get_sessionmaker()() as db:
        await db.execute(sql_text("DROP TABLE IF EXISTS chunks_vec"))
        await db.execute(delete(EmbeddingConfig))
        await db.commit()

        chunks = list((await db.execute(select(Chunk))).scalars())
        if not chunks:
            return {"chunks": 0, "embedded": 0}
        vectors = await embed_documents([c.text for c in chunks])
        ok = await store_vectors(db, [(c.id, v) for c, v in zip(chunks, vectors, strict=True)])
        return {"chunks": len(chunks), "embedded": len(vectors) if ok else 0}
