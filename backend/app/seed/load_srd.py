import logging

log = logging.getLogger("hallucinatingdm.seed")


async def seed_srd() -> None:
    """Idempotently load bundled SRD 5.1 JSON into srd_entries. Lands in Phase 3."""
    log.info("SRD seed: no bundled data yet (Phase 3)")
