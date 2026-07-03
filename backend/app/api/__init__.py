from fastapi import APIRouter

from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.campaigns import router as campaigns_router
from app.api.characters import router as characters_router
from app.api.combat import router as combat_router
from app.api.dm import router as dm_router
from app.api.documents import router as documents_router
from app.api.scenes import router as scenes_router
from app.api.srd import router as srd_router
from app.api.world import router as world_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(campaigns_router)
api_router.include_router(scenes_router)
api_router.include_router(characters_router)
api_router.include_router(srd_router)
api_router.include_router(admin_router)
api_router.include_router(documents_router)
api_router.include_router(world_router)
api_router.include_router(combat_router)
api_router.include_router(dm_router)
