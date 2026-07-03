import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings

log = logging.getLogger("hallucinatingdm")
logging.basicConfig(level=logging.INFO)


def _run_migrations_sync() -> None:
    from alembic.config import Config

    from alembic import command

    cfg = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
    cfg.set_main_option(
        "script_location",
        str(Path(__file__).resolve().parent.parent / "alembic"),
    )
    command.upgrade(cfg, "head")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)

    # Alembic is sync; its env.py calls asyncio.run, so hop to a thread.
    await asyncio.to_thread(_run_migrations_sync)
    log.info("database migrated")

    from app.seed.load_srd import seed_srd

    await seed_srd()

    from app.rag.ingest import ingest_srd_prose

    await ingest_srd_prose()

    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="HallucinatingDM", lifespan=lifespan)

    from app.api import api_router
    from app.api.ws import router as ws_router

    app.include_router(api_router, prefix="/api/v1")
    app.include_router(ws_router)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    # Production: serve the built frontend from the same origin.
    static_dir = settings.static_dir
    if static_dir and static_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")
        index = static_dir / "index.html"

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str) -> FileResponse:
            candidate = (static_dir / path).resolve()
            if (
                path
                and candidate.is_file()
                and candidate.is_relative_to(static_dir.resolve())
            ):
                return FileResponse(candidate)
            return FileResponse(index)

    return app


app = create_app()
