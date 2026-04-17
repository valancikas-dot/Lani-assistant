"""ORM model for structured memory entries."""

import datetime
from sqlalchemy import Integer, String, Text, Float, Boolean, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column
from typing import Optional

from app.core.database import Base


class MemoryEntry(Base):
    """
    A single structured memory entry.

    Categories (enforced by the service layer):
      user_preferences   – language, voice, folder paths, naming style …
      workflow_preferences – sort style, approval thresholds, tool defaults …
      task_history       – completed plan summaries
      suggestions        – auto-generated recommendation pending user decision
      facts              – explicit facts about the user ("my birthday is Jan 15")
    """

    __tablename__ = "memory_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    category: Mapped[str] = mapped_column(
        String(60), nullable=False, index=True
    )

    key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    """Dot-notation key, e.g. 'preferred_output_folder' or 'sort_downloads.group_by'."""

    value: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    """Arbitrary JSON payload – always a dict for forward-compat."""

    source: Mapped[str] = mapped_column(
        String(80), nullable=False, default="user_explicit"
    )

    confidence: Mapped[float] = mapped_column(
        Float, nullable=False, default=1.0
    )

    pinned: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active"
    )

    # Embedding vector stored as a JSON float array.
    # Populated lazily by memory_service when OPENAI_API_KEY is available.
    # Enables semantic similarity search instead of keyword scanning.
    embedding: Mapped[Optional[list]] = mapped_column(
        JSON, nullable=True, default=None
    )

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
        nullable=False,
    )
