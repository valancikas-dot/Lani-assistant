"""Token economy routes – balance, history, admin top-up."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, require_admin
from app.core.database import get_db
from app.models.token_ledger import TokenBalance, TokenTransaction
from app.models.user import User
from app.services import token_service

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class BalanceOut(BaseModel):
    user_id: int
    email: str
    balance: float
    lifetime_purchased: float
    lifetime_used: float
    is_admin: bool


class TopUpRequest(BaseModel):
    user_email: str
    amount: float
    description: str = "Admin top-up"


class TopUpResponse(BaseModel):
    user_email: str
    new_balance: float


class TransactionOut(BaseModel):
    id: int
    amount: float
    tx_type: str
    description: str
    balance_after: float
    created_at: str


class TransactionListOut(BaseModel):
    transactions: list[TransactionOut]


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/tokens/balance", response_model=BalanceOut)
async def get_balance(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BalanceOut:
    """Return the current user's token balance."""
    balance = await token_service.get_balance(db, user)
    safe = 999_999_999.0 if balance == float("inf") else balance

    # Fetch lifetime stats (admin doesn't have a real row but we handle that)
    result = await db.execute(
        select(TokenBalance).where(TokenBalance.user_id == user.id)
    )
    row = result.scalar_one_or_none()

    return BalanceOut(
        user_id=user.id,
        email=user.email,
        balance=safe,
        lifetime_purchased=row.lifetime_purchased if row else 0.0,
        lifetime_used=row.lifetime_used if row else 0.0,
        is_admin=user.is_admin or token_service.is_admin_email(user.email),
    )


@router.get("/tokens/history", response_model=TransactionListOut)
async def get_history(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TransactionListOut:
    """Return the last 50 token transactions for the current user."""
    result = await db.execute(
        select(TokenTransaction)
        .where(TokenTransaction.user_id == user.id)
        .order_by(TokenTransaction.id.desc())
        .limit(50)
    )
    rows = result.scalars().all()
    return TransactionListOut(
        transactions=[
            TransactionOut(
                id=r.id,
                amount=r.amount,
                tx_type=r.tx_type,
                description=r.description,
                balance_after=r.balance_after,
                created_at=r.created_at.isoformat(),
            )
            for r in rows
        ]
    )


@router.post("/tokens/topup", response_model=TopUpResponse)
async def admin_topup(
    payload: TopUpRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> TopUpResponse:
    """Admin only – add tokens to any user's balance."""
    result = await db.execute(
        select(User).where(User.email == payload.user_email.lower())
    )
    target: User | None = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    new_balance = await token_service.top_up(
        db, target, payload.amount, payload.description
    )
    return TopUpResponse(user_email=target.email, new_balance=new_balance)


@router.get("/tokens/users", response_model=list[BalanceOut])
async def list_all_balances(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[BalanceOut]:
    """Admin only – list all users with their balances."""
    users_result = await db.execute(select(User))
    users = users_result.scalars().all()

    out: list[BalanceOut] = []
    for u in users:
        balance = await token_service.get_balance(db, u)
        safe = 999_999_999.0 if balance == float("inf") else balance
        bal_result = await db.execute(
            select(TokenBalance).where(TokenBalance.user_id == u.id)
        )
        row = bal_result.scalar_one_or_none()
        out.append(
            BalanceOut(
                user_id=u.id,
                email=u.email,
                balance=safe,
                lifetime_purchased=row.lifetime_purchased if row else 0.0,
                lifetime_used=row.lifetime_used if row else 0.0,
                is_admin=u.is_admin or token_service.is_admin_email(u.email),
            )
        )
    return out
