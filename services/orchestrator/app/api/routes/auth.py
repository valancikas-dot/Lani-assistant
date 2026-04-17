"""Auth routes – register and login."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import (
    create_access_token,
    get_current_user,
    hash_password,
    is_admin_email,
    verify_password,
)
from app.core.database import get_db
from app.models.user import User
from app.services import token_service

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    email: str
    is_admin: bool


class MeResponse(BaseModel):
    user_id: int
    email: str
    is_admin: bool
    token_balance: float  # "inf" not JSON-serialisable → we'll cap it


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/auth/register", response_model=AuthResponse, status_code=201)
async def register(
    payload: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> AuthResponse:
    """Register a new user account."""
    # Check duplicate
    result = await db.execute(select(User).where(User.email == payload.email.lower()))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    admin = is_admin_email(payload.email)
    user = User(
        email=payload.email.lower(),
        hashed_password=hash_password(payload.password),
        is_admin=admin,
    )
    db.add(user)
    await db.flush()

    # Create balance row with welcome bonus
    await token_service._get_or_create_balance(db, user)

    token = create_access_token(user.id, user.email)
    return AuthResponse(
        access_token=token,
        user_id=user.id,
        email=user.email,
        is_admin=user.is_admin,
    )


@router.post("/auth/login", response_model=AuthResponse)
async def login(
    payload: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> AuthResponse:
    """Authenticate and return a JWT access token."""
    result = await db.execute(select(User).where(User.email == payload.email.lower()))
    user: User | None = result.scalar_one_or_none()

    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")

    token = create_access_token(user.id, user.email)
    return AuthResponse(
        access_token=token,
        user_id=user.id,
        email=user.email,
        is_admin=user.is_admin,
    )


@router.get("/auth/me", response_model=MeResponse)
async def me(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MeResponse:
    """Return the current user's profile and token balance."""
    balance = await token_service.get_balance(db, user)
    # JSON can't encode infinity – return large sentinel for admin
    safe_balance = 999_999_999.0 if balance == float("inf") else balance
    return MeResponse(
        user_id=user.id,
        email=user.email,
        is_admin=user.is_admin,
        token_balance=safe_balance,
    )
