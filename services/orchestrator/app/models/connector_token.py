"""ORM model for encrypted OAuth tokens tied to a ConnectorAccount."""

import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ConnectorToken(Base):
    """Stores encrypted OAuth tokens for a ConnectorAccount.

    A single account row may have multiple token rows if we refresh
    incrementally, but in practice there is one active row per account.
    Tokens are encrypted at rest using Fernet (see connectors/base.py).
    """

    __tablename__ = "connector_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # FK back to the owning account
    account_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("connector_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Fernet-encrypted JSON blob containing:
    #   {"access_token": "...", "refresh_token": "...",
    #    "token_uri": "...", "client_id": "...", "client_secret": "...",
    #    "scopes": ["..."]}
    encrypted_credentials: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=False,
        default=datetime.datetime.utcnow,
    )
    expires_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    refreshed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
