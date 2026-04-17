"""ORM model for a connected third-party account (e.g. Google Drive, Gmail)."""

import datetime
from sqlalchemy import DateTime, Integer, String, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ConnectorAccount(Base):
    """One row per connected service/account combination.

    Multiple Google accounts are represented as multiple rows, each with a
    different ``account_email``.
    """

    __tablename__ = "connector_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # e.g. "google_drive" | "gmail" | "google_calendar"
    provider: Mapped[str] = mapped_column(String(60), nullable=False, index=True)

    # Human-readable: the authenticated email address returned by the provider
    account_email: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    # Display name (from OAuth userinfo, if available)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    # Comma-separated list of OAuth scopes that were granted
    scopes_granted: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Whether this account is currently active / usable
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    connected_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=False,
        default=datetime.datetime.utcnow,
    )
    last_used_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
