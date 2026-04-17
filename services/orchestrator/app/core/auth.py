"""Authentication helpers: password hashing, JWT creation/verification, admin check."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

# ── Config ────────────────────────────────────────────────────────────────────

# Admin email – always free, unlimited tokens
ADMIN_EMAIL: str = "valancikas@gmail.com"

# JWT settings
_JWT_ALGORITHM = "HS256"
_ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days

def _get_secret() -> str:
    """Return the JWT secret key.  Falls back to a dev key if SECRET_KEY not set."""
    from app.core.config import settings
    key = settings.SECRET_KEY or os.environ.get("SECRET_KEY", "")
    if not key:
        # Development-only deterministic key
        key = "lani-dev-secret-key-change-in-production-2026"
    return key


# ── Password hashing ──────────────────────────────────────────────────────────

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return _pwd_ctx.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_ctx.verify(plain, hashed)


# ── JWT ───────────────────────────────────────────────────────────────────────

def create_access_token(user_id: int, email: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=_ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "email": email,
        "exp": expire,
    }
    return jwt.encode(payload, _get_secret(), algorithm=_JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Decode and validate JWT.  Raises JWTError on invalid/expired tokens."""
    return jwt.decode(token, _get_secret(), algorithms=[_JWT_ALGORITHM])


# ── FastAPI dependency ────────────────────────────────────────────────────────

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db

_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


async def get_current_user_optional(
    token: Optional[str] = Depends(_oauth2_scheme),
    db: AsyncSession = Depends(get_db),
):
    """Return the User row or None if no valid token supplied."""
    if not token:
        return None
    try:
        payload = decode_access_token(token)
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        return None

    from app.models.user import User
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_current_user(
    token: Optional[str] = Depends(_oauth2_scheme),
    db: AsyncSession = Depends(get_db),
):
    """Return the authenticated User or raise 401."""
    user = await get_current_user_optional(token=token, db=db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def require_admin(user=Depends(get_current_user)):
    """Raise 403 if the current user is not an admin."""
    if not user.is_admin and user.email.lower() != ADMIN_EMAIL.lower():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    return user


def is_admin_email(email: str) -> bool:
    return email.strip().lower() == ADMIN_EMAIL.lower()
