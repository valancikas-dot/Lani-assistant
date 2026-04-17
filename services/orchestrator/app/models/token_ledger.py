"""ORM models for the token economy – balances and transaction ledger."""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TokenBalance(Base):
    """Current token balance per user (one row per user)."""

    __tablename__ = "token_balances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    balance: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    lifetime_purchased: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    lifetime_used: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TokenTransaction(Base):
    """Immutable ledger entry for every credit/debit."""

    __tablename__ = "token_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # positive = top-up / refund, negative = usage charge
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    # "topup" | "usage" | "refund" | "admin_grant"
    tx_type: Mapped[str] = mapped_column(String(30), nullable=False)
    description: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    # snapshot of balance after this transaction
    balance_after: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
