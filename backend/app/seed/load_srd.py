import json
import logging
from pathlib import Path

from sqlalchemy import func, select

from app.db import get_sessionmaker
from app.models import SrdEntry

log = logging.getLogger("landl.seed")

SRD_DIR = Path(__file__).resolve().parent / "srd"

KINDS = [
    "race",
    "class",
    "background",
    "spell",
    "equipment",
    "magic-item",
    "monster",
    "condition",
    "rule",
    "rollable-table",
]


async def seed_srd() -> None:
    """Idempotently load bundled SRD 5.1 JSON into srd_entries."""
    async with get_sessionmaker()() as db:
        for kind in KINDS:
            path = SRD_DIR / f"{kind}.json"
            if not path.exists():
                continue
            entries = json.loads(path.read_text())
            existing = (
                await db.execute(
                    select(func.count(SrdEntry.id)).where(SrdEntry.kind == kind)
                )
            ).scalar_one()
            if existing >= len(entries):
                continue
            have = {
                slug
                for (slug,) in await db.execute(
                    select(SrdEntry.slug).where(SrdEntry.kind == kind)
                )
            }
            added = 0
            for entry in entries:
                if entry["slug"] in have:
                    continue
                db.add(
                    SrdEntry(
                        kind=kind,
                        slug=entry["slug"],
                        name=entry["name"],
                        data_json=entry["data"],
                    )
                )
                added += 1
            await db.commit()
            if added:
                log.info("SRD seed: %s +%d entries", kind, added)
