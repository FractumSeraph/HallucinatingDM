from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import forbidden, not_found
from app.db import get_db
from app.models import Campaign, CampaignMember, User
from app.services.auth_service import COOKIE_NAME, decode_access_token

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(
    db: DbSession,
    hdm_session: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None,
) -> User:
    if not hdm_session:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    user_id = decode_access_token(hdm_session)
    if not user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown user")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_membership(
    db: AsyncSession, campaign_id: str, user_id: str
) -> CampaignMember | None:
    result = await db.execute(
        select(CampaignMember).where(
            CampaignMember.campaign_id == campaign_id,
            CampaignMember.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def require_campaign_member(
    campaign_id: str, db: DbSession, user: CurrentUser
) -> CampaignMember:
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise not_found("Campaign")
    member = await get_membership(db, campaign_id, user.id)
    if not member:
        raise forbidden("You are not a member of this campaign")
    return member


async def require_campaign_dm(
    campaign_id: str, db: DbSession, user: CurrentUser
) -> CampaignMember:
    member = await require_campaign_member(campaign_id, db, user)
    if member.role != "dm":
        raise forbidden("DM access required")
    return member


Membership = Annotated[CampaignMember, Depends(require_campaign_member)]
DmMembership = Annotated[CampaignMember, Depends(require_campaign_dm)]
