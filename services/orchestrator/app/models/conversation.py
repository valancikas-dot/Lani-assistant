"""ORM model for short-term conversation history."""

import datetime
from sqlalchemy import Integer, String, Text, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ConversationMessage(Base):
    """
    A single message in the conversation history.
    Used to provide context to the LLM across multiple turns.

    Roles: "user" | "assistant"
    session_id: groups messages into one session (default "default").
    Auto-pruned to the last MAX_HISTORY messages per session.
    """

    __tablename__ = "conversation_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    session_id: Mapped[str] = mapped_column(
        String(80), nullable=False, default="default", index=True
    )

    role: Mapped[str] = mapped_column(String(20), nullable=False)
    """user | assistant"""

    content: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_conversation_session_created", "session_id", "created_at"),
    )
