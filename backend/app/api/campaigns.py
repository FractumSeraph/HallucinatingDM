from datetime import datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import (
    CurrentUser,
    DbSession,
    get_membership,
    require_campaign_dm,
    require_campaign_member,
)
from app.api.errors import bad_request, forbidden, not_found
from app.models import Campaign, CampaignMember, Summary, User

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    settings: dict[str, Any] = {}


class CampaignPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    settings: dict[str, Any] | None = None
    world_clock: str | None = None


class CampaignOut(BaseModel):
    id: str
    name: str
    description: str
    owner_id: str
    invite_code: str
    settings_json: dict[str, Any]
    world_clock: str
    my_role: str | None = None

    model_config = {"from_attributes": True}


class MemberOut(BaseModel):
    user_id: str
    display_name: str
    role: str


class JoinRequest(BaseModel):
    invite_code: str


def _campaign_out(campaign: Campaign, role: str | None) -> CampaignOut:
    out = CampaignOut.model_validate(campaign)
    out.my_role = role
    if role != "dm":
        out.invite_code = ""  # only the DM shares the invite link
    return out


@router.get("", response_model=list[CampaignOut])
async def list_my_campaigns(db: DbSession, user: CurrentUser) -> list[CampaignOut]:
    result = await db.execute(
        select(Campaign, CampaignMember.role)
        .join(CampaignMember, CampaignMember.campaign_id == Campaign.id)
        .where(CampaignMember.user_id == user.id)
        .order_by(Campaign.created_at.desc())
    )
    return [_campaign_out(c, role) for c, role in result.all()]


@router.post("", response_model=CampaignOut)
async def create_campaign(
    body: CampaignCreate, db: DbSession, user: CurrentUser
) -> CampaignOut:
    campaign = Campaign(
        name=body.name,
        description=body.description,
        owner_id=user.id,
        settings_json=body.settings,
    )
    db.add(campaign)
    await db.flush()
    db.add(CampaignMember(campaign_id=campaign.id, user_id=user.id, role="dm"))
    await db.commit()
    return _campaign_out(campaign, "dm")


@router.post("/join", response_model=CampaignOut)
async def join_campaign(body: JoinRequest, db: DbSession, user: CurrentUser) -> CampaignOut:
    result = await db.execute(
        select(Campaign).where(Campaign.invite_code == body.invite_code.strip())
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise bad_request("Invalid invite code")
    member = await get_membership(db, campaign.id, user.id)
    if member:
        return _campaign_out(campaign, member.role)
    db.add(CampaignMember(campaign_id=campaign.id, user_id=user.id, role="player"))
    await db.commit()
    return _campaign_out(campaign, "player")


@router.get("/{campaign_id}", response_model=CampaignOut)
async def get_campaign(campaign_id: str, db: DbSession, user: CurrentUser) -> CampaignOut:
    member = await require_campaign_member(campaign_id, db, user)
    campaign = await db.get(Campaign, campaign_id)
    assert campaign
    return _campaign_out(campaign, member.role)


@router.patch("/{campaign_id}", response_model=CampaignOut)
async def update_campaign(
    campaign_id: str, body: CampaignPatch, db: DbSession, user: CurrentUser
) -> CampaignOut:
    member = await require_campaign_dm(campaign_id, db, user)
    campaign = await db.get(Campaign, campaign_id)
    assert campaign
    if body.name is not None:
        campaign.name = body.name
    if body.description is not None:
        campaign.description = body.description
    if body.settings is not None:
        campaign.settings_json = body.settings
    if body.world_clock is not None:
        campaign.world_clock = body.world_clock
    await db.commit()
    return _campaign_out(campaign, member.role)


@router.delete("/{campaign_id}")
async def delete_campaign(campaign_id: str, db: DbSession, user: CurrentUser) -> dict[str, bool]:
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise not_found("Campaign")
    if campaign.owner_id != user.id:
        raise forbidden("Only the campaign owner can delete it")
    await db.delete(campaign)
    await db.commit()
    return {"ok": True}


class RecapEntry(BaseModel):
    scene_id: str | None
    content: str
    created_at: datetime


class RecapsOut(BaseModel):
    campaign_summary: str
    recaps: list[RecapEntry]


@router.get("/{campaign_id}/recaps", response_model=RecapsOut)
async def get_recaps(campaign_id: str, db: DbSession, user: CurrentUser) -> RecapsOut:
    """'Previously on…' — the campaign summary plus the last few scene recaps."""
    await require_campaign_member(campaign_id, db, user)
    campaign = await db.get(Campaign, campaign_id)
    assert campaign
    rows = list(
        (
            await db.execute(
                select(Summary)
                .where(Summary.campaign_id == campaign_id, Summary.scope == "scene")
                .order_by(Summary.created_at.desc())
                .limit(5)
            )
        ).scalars()
    )
    return RecapsOut(
        campaign_summary=campaign.summary,
        recaps=[
            RecapEntry(scene_id=r.ref_id, content=r.content, created_at=r.created_at)
            for r in rows
        ],
    )


@router.get("/{campaign_id}/members", response_model=list[MemberOut])
async def list_members(campaign_id: str, db: DbSession, user: CurrentUser) -> list[MemberOut]:
    await require_campaign_member(campaign_id, db, user)
    result = await db.execute(
        select(CampaignMember, User.display_name)
        .join(User, User.id == CampaignMember.user_id)
        .where(CampaignMember.campaign_id == campaign_id)
        .order_by(CampaignMember.created_at)
    )
    return [
        MemberOut(user_id=m.user_id, display_name=name, role=m.role)
        for m, name in result.all()
    ]
