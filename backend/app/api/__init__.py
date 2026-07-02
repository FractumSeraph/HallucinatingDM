from fastapi import APIRouter

from app.api.auth import router as auth_router
from app.api.campaigns import router as campaigns_router
from app.api.scenes import router as scenes_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(campaigns_router)
api_router.include_router(scenes_router)
