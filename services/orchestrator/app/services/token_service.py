"""Token economy service – check balance, deduct, top-up."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import is_admin_email
from app.models.token_ledger import TokenBalance, TokenTransaction
from app.models.user import User

# ── Token cost table ──────────────────────────────────────────────────────────
# Costs are in "Lani tokens".  1 token ≈ 1 OpenAI input token (but priced higher).
# Clients see "Lani tokens"; we pay OpenAI with real tokens and keep the margin.

COST_PER_CHAT_TOKEN = 1.0          # 1 token per LLM input/output token
COST_PER_TTS_CHAR = 0.05           # per character (OpenAI TTS)
COST_PER_IMAGE = 500.0             # per DALL·E image
COST_PER_VIDEO_SECOND = 200.0      # per second of Runway video
COST_PER_SEARCH = 50.0             # per Tavily search request
NEW_USER_GRANT = 5_000.0           # free tokens on registration


async def _get_or_create_balance(db: AsyncSession, user: User) -> TokenBalance:
    result = await db.execute(
        select(TokenBalance).where(TokenBalance.user_id == user.id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = TokenBalance(
            user_id=user.id,
            balance=NEW_USER_GRANT,
            lifetime_purchased=NEW_USER_GRANT,
            lifetime_used=0.0,
        )
        db.add(row)
        # Record the grant transaction
        db.add(
            TokenTransaction(
                user_id=user.id,
                amount=NEW_USER_GRANT,
                tx_type="admin_grant",
                description="Welcome bonus",
                balance_after=NEW_USER_GRANT,
            )
        )
        await db.flush()
    return row


async def get_balance(db: AsyncSession, user: User) -> float:
    """Return current token balance.  Admin email → always returns infinity sentinel."""
    if is_admin_email(user.email):
        return float("inf")
    row = await _get_or_create_balance(db, user)
    return row.balance


async def deduct(
    db: AsyncSession,
    user: User,
    amount: float,
    description: str = "",
) -> tuple[bool, float]:
    """Deduct `amount` tokens from the user's balance.

    Returns:
        (success, balance_after)
        success=False if insufficient balance (admin always True).
    """
    if is_admin_email(user.email):
        return True, float("inf")

    row = await _get_or_create_balance(db, user)

    if row.balance < amount:
        return False, row.balance

    row.balance -= amount
    row.lifetime_used += amount
    db.add(
        TokenTransaction(
            user_id=user.id,
            amount=-amount,
            tx_type="usage",
            description=description or "AI usage",
            balance_after=row.balance,
        )
    )
    await db.flush()
    return True, row.balance


async def top_up(
    db: AsyncSession,
    user: User,
    amount: float,
    description: str = "Manual top-up",
) -> float:
    """Add tokens to a user's balance.  Returns new balance."""
    row = await _get_or_create_balance(db, user)
    row.balance += amount
    row.lifetime_purchased += amount
    db.add(
        TokenTransaction(
            user_id=user.id,
            amount=amount,
            tx_type="topup",
            description=description,
            balance_after=row.balance,
        )
    )
    await db.flush()
    return row.balance
