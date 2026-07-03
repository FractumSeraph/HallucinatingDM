from typing import Any

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.api.errors import bad_request, not_found
from app.models import SrdEntry
from app.seed.load_srd import KINDS

router = APIRouter(prefix="/srd", tags=["srd"])


def _summary(entry: SrdEntry) -> dict[str, Any]:
    out: dict[str, Any] = {"slug": entry.slug, "name": entry.name}
    data = entry.data_json
    if entry.kind == "spell":
        out["level"] = data.get("level")
        out["school"] = data.get("school")
    elif entry.kind == "monster":
        out["cr"] = data.get("cr")
        out["type"] = data.get("type")
    elif entry.kind == "equipment":
        out["category"] = data.get("category")
    elif entry.kind == "magic-item":
        out["rarity"] = data.get("rarity")
    return out


@router.get("/{kind}")
async def list_srd(
    kind: str, db: DbSession, _user: CurrentUser, q: str = "", limit: int = 500
) -> list[dict[str, Any]]:
    if kind not in KINDS:
        raise bad_request(f"Unknown SRD kind '{kind}'")
    query = select(SrdEntry).where(SrdEntry.kind == kind).order_by(SrdEntry.name)
    if q:
        query = query.where(SrdEntry.name.ilike(f"%{q}%"))
    result = await db.execute(query.limit(min(limit, 1000)))
    return [_summary(e) for e in result.scalars()]


@router.get("/{kind}/{slug}")
async def get_srd_entry(
    kind: str, slug: str, db: DbSession, _user: CurrentUser
) -> dict[str, Any]:
    if kind not in KINDS:
        raise bad_request(f"Unknown SRD kind '{kind}'")
    result = await db.execute(
        select(SrdEntry).where(SrdEntry.kind == kind, SrdEntry.slug == slug)
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise not_found(f"SRD {kind}")
    return {"slug": entry.slug, "name": entry.name, "kind": entry.kind, "data": entry.data_json}
