"""ORM model for user feedback on assistant responses."""

import datetime
from sqlalchemy import Integer, String, Text, Float, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class FeedbackEntry(Base):
    """
    Stores user ratings (👍/👎) on individual assistant responses.

    rating:   1.0 = positive (thumbs up), 0.0 = negative (thumbs down)
    command:  the original user command
    response: assistant's response text (first 500 chars)
    tool:     which tool was used (chat, web_search, …)
    comment:  optional free-text comment from the user
    """

    __tablename__ = "feedback_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    command: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tool: Mapped[str] = mapped_column(String(80), nullable=False, default="chat")
    rating: Mapped[float] = mapped_column(Float, nullable=False)
    """1.0 = positive, 0.0 = negative"""

    comment: Mapped[str] = mapped_column(Text, nullable=False, default="")
    session_id: Mapped[str] = mapped_column(String(80), nullable=False, default="default")

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_feedback_tool_rating", "tool", "rating"),
        Index("ix_feedback_created", "created_at"),
    )
