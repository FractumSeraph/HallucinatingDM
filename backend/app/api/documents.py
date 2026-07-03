from typing import Any

from fastapi import APIRouter, BackgroundTasks, UploadFile
from sqlalchemy import delete, select

from app.api.deps import CurrentUser, DbSession, require_campaign_dm, require_campaign_member
from app.api.errors import bad_request, not_found
from app.config import get_settings
from app.db import new_id
from app.models import Chunk, Document
from app.rag.ingest import ingest_document
from app.rag.search import search_books

router = APIRouter(tags=["documents"])

MAX_PDF_BYTES = 100 * 1024 * 1024


def _doc_out(d: Document) -> dict[str, Any]:
    return {
        "id": d.id,
        "title": d.title,
        "filename": d.filename,
        "status": d.status,
        "progress": d.progress,
        "page_count": d.page_count,
        "chunk_count": d.chunk_count,
        "error": d.error,
    }


@router.get("/campaigns/{campaign_id}/documents")
async def list_documents(
    campaign_id: str, db: DbSession, user: CurrentUser
) -> list[dict[str, Any]]:
    await require_campaign_member(campaign_id, db, user)
    result = await db.execute(
        select(Document)
        .where((Document.campaign_id == campaign_id) | (Document.campaign_id.is_(None)))
        .order_by(Document.created_at)
    )
    return [_doc_out(d) for d in result.scalars()]


@router.post("/campaigns/{campaign_id}/documents")
async def upload_document(
    campaign_id: str,
    file: UploadFile,
    background: BackgroundTasks,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, Any]:
    await require_campaign_dm(campaign_id, db, user)
    filename = file.filename or "upload.pdf"
    if not filename.lower().endswith(".pdf"):
        raise bad_request("Only PDF uploads are supported")

    content = await file.read()
    if len(content) > MAX_PDF_BYTES:
        raise bad_request("PDF is too large (100 MB max)")
    if not content.startswith(b"%PDF"):
        raise bad_request("That file doesn't look like a PDF")

    settings = get_settings()
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{new_id()}.pdf"
    path = settings.uploads_dir / stored_name
    path.write_bytes(content)

    document = Document(
        campaign_id=campaign_id,
        title=filename.rsplit(".", 1)[0],
        filename=stored_name,
        status="processing",
        uploaded_by=user.id,
    )
    db.add(document)
    await db.commit()

    background.add_task(ingest_document, document.id, str(path))
    return _doc_out(document)


@router.delete("/documents/{document_id}")
async def delete_document(
    document_id: str, db: DbSession, user: CurrentUser
) -> dict[str, bool]:
    document = await db.get(Document, document_id)
    if not document:
        raise not_found("Document")
    if document.campaign_id is None:
        raise bad_request("The bundled SRD cannot be deleted")
    await require_campaign_dm(document.campaign_id, db, user)

    settings = get_settings()
    if document.filename:
        (settings.uploads_dir / document.filename).unlink(missing_ok=True)
    await db.execute(delete(Chunk).where(Chunk.document_id == document.id))
    await db.delete(document)
    await db.commit()
    return {"ok": True}


@router.get("/campaigns/{campaign_id}/search")
async def search(
    campaign_id: str, q: str, db: DbSession, user: CurrentUser
) -> list[dict[str, Any]]:
    await require_campaign_member(campaign_id, db, user)
    if not q.strip():
        return []
    hits = await search_books(db, campaign_id, q.strip())
    return [
        {
            "text": h.text,
            "section_path": h.section_path,
            "document_title": h.document_title,
            "page_start": h.page_start,
            "page_end": h.page_end,
            "score": h.score,
        }
        for h in hits
    ]
