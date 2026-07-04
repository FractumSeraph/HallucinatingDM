from fastapi import APIRouter, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.api.errors import bad_request, forbidden
from app.config import get_settings
from app.models import User
from app.services.auth_service import (
    COOKIE_NAME,
    create_access_token,
    hash_password,
    verify_password,
)
from app.services.settings_service import get_setting

router = APIRouter(prefix="/auth", tags=["auth"])

INSTANCE_SETTINGS_KEY = "instance"


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    display_name: str = Field(min_length=1, max_length=80)
    invite_code: str = ""


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: str
    email: str
    display_name: str
    is_admin: bool

    model_config = {"from_attributes": True}


def _set_session_cookie(response: Response, user_id: str) -> None:
    settings = get_settings()
    response.set_cookie(
        COOKIE_NAME,
        create_access_token(user_id),
        max_age=settings.access_token_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )


@router.get("/registration")
async def registration_mode() -> dict[str, str]:
    """Public: how signup works on this instance, so the register page can show
    an invite field or a 'closed' notice. Never returns the invite code."""
    instance = await get_setting(INSTANCE_SETTINGS_KEY)
    return {"mode": instance.get("signup_mode", "open")}


@router.post("/register", response_model=UserOut)
async def register(body: RegisterRequest, db: DbSession, response: Response) -> User:
    existing = await db.execute(select(User).where(User.email == body.email.lower()))
    if existing.scalar_one_or_none():
        raise bad_request("An account with this email already exists")

    user_count = (await db.execute(select(func.count(User.id)))).scalar_one()
    # The very first account bootstraps the install (becomes admin) and is
    # always allowed; after that, honor the instance signup policy.
    if user_count > 0:
        instance = await get_setting(INSTANCE_SETTINGS_KEY)
        mode = instance.get("signup_mode", "open")
        if mode == "closed":
            raise forbidden("Registration is closed on this instance.")
        if mode == "invite":
            expected = instance.get("signup_code", "")
            if not expected or body.invite_code.strip() != expected:
                raise forbidden("A valid invite code is required to register.")

    user = User(
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        display_name=body.display_name,
        is_admin=user_count == 0,  # first account administers this install
    )
    db.add(user)
    await db.commit()
    _set_session_cookie(response, user.id)
    return user


@router.post("/login", response_model=UserOut)
async def login(body: LoginRequest, db: DbSession, response: Response) -> User:
    result = await db.execute(select(User).where(User.email == body.email.lower()))
    user = result.scalar_one_or_none()
    if not user or not verify_password(user.password_hash, body.password):
        raise bad_request("Invalid email or password")
    _set_session_cookie(response, user.id)
    return user


@router.post("/logout")
async def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> User:
    return user
